import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterField,
                       QgsProcessingParameterExtent,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterFolderDestination,
                       QgsProcessingParameterFile,
                       QgsProcessingParameterExtent,
                       QgsProcessingException,
                       QgsVectorLayer,
                       QgsVectorFileWriter,
                       QgsFeature,
                       QgsField)
import json
from osgeo import gdal, osr

try:
    from pykrige.ok import OrdinaryKriging
except ImportError:
    OrdinaryKriging = None

class KrigingAlgorithm(QgsProcessingAlgorithm):
    INPUT = 'INPUT'
    FIELD = 'FIELD'
    EXTENT = 'EXTENT'
    CELLSIZE = 'CELLSIZE'
    VARIOGRAM_JSON = 'VARIOGRAM_JSON'
    OUTPUT_DIR = 'OUTPUT_DIR'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return KrigingAlgorithm()

    def name(self):
        return 'kriging_ordinario'

    def displayName(self):
        return self.tr('Interpolación Kriging Ordinario')

    def group(self):
        return self.tr('Interpolación')

    def groupId(self):
        return 'interpolacion'

    def shortHelpString(self):
        return self.tr(
            "Esta herramienta realiza interpolación Kriging Ordinario, iterando sobre modelos de variograma "
            "('spherical', 'exponential', 'gaussian', 'linear', 'power') mediante validación cruzada. "
            "Calcula la semivarianza, grafica el modelo óptimo y genera un reporte HTML y el raster de salida."
        )

    def checkParameterValues(self, parameters, context):
        if OrdinaryKriging is None:
            return False, self.tr("La librería 'pykrige' no está instalada. Usa la opción 'Instalar Dependencias' del plugin.")
        return super().checkParameterValues(parameters, context)

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT, 
                self.tr('Capa de puntos de entrada'), 
                [QgsProcessing.TypeVectorPoint]
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.FIELD,
                self.tr('Campo de interpolación (Z)'),
                None,
                self.INPUT,
                QgsProcessingParameterField.Numeric
            )
        )
        self.addParameter(
            QgsProcessingParameterExtent(
                self.EXTENT,
                self.tr('Extensión del estudio')
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.CELLSIZE,
                self.tr('Resolución de celda (Raster)'),
                QgsProcessingParameterNumber.Double,
                10.0, False, 0.0001
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.VARIOGRAM_JSON,
                self.tr('Archivo JSON de Variograma (Opcional, de paso 2)'),
                extension='json',
                optional=True
            )
        )
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_DIR,
                self.tr('Carpeta de salida para reportes y raster')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        # 1. Obtener parámetros (usar parameterAsVectorLayer para compatibilidad con EXTENT)
        layer = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        field_name = self.parameterAsString(parameters, self.FIELD, context)
        cell_size = self.parameterAsDouble(parameters, self.CELLSIZE, context)
        var_json_path = self.parameterAsString(parameters, self.VARIOGRAM_JSON, context)
        output_dir = self.parameterAsString(parameters, self.OUTPUT_DIR, context)

        if layer is None:
            raise QgsProcessingException("No se pudo cargar la capa de entrada.")

        # Obtener extensión usando layer.crs() (patrón probado en GeoArchaeo)
        extent_geom = self.parameterAsExtent(parameters, self.EXTENT, context, layer.crs())
        xmin, xmax = extent_geom.xMinimum(), extent_geom.xMaximum()
        ymin, ymax = extent_geom.yMinimum(), extent_geom.yMaximum()
        
        # Fallback: si sigue siendo NaN, usar el bounding box de la capa + buffer 5%
        if np.isnan(xmin) or np.isnan(xmax) or np.isnan(ymin) or np.isnan(ymax) or xmin == xmax or ymin == ymax:
            feedback.pushInfo("⚠ Extensión del diálogo inválida. Usando extensión de la capa de entrada con buffer 5%...")
            src_extent = layer.extent()
            xmin, xmax = src_extent.xMinimum(), src_extent.xMaximum()
            ymin, ymax = src_extent.yMinimum(), src_extent.yMaximum()
            buffer_x = (xmax - xmin) * 0.05
            buffer_y = (ymax - ymin) * 0.05
            xmin -= buffer_x
            xmax += buffer_x
            ymin -= buffer_y
            ymax += buffer_y
        
        feedback.pushInfo(f"Extensión final: xmin={xmin}, xmax={xmax}, ymin={ymin}, ymax={ymax}")
        feedback.pushInfo(f"CRS: {layer.crs().authid()}")
        feedback.pushInfo(f"Resolución de celda: {cell_size}")

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # Extraer puntos
        field_index = layer.fields().lookupField(field_name)
        features = list(layer.getFeatures())
        coords = np.zeros((len(features), 2))
        values = np.zeros(len(features))
        for i, feat in enumerate(features):
            geom = feat.geometry()
            pt = geom.asPoint()
            coords[i, 0] = pt.x()
            coords[i, 1] = pt.y()
            values[i] = float(feat.attributes()[field_index])

        n = len(values)
        if n < 10:
            raise QgsProcessingException("No hay suficientes puntos para Kriging (mínimo 10).")

        x = coords[:, 0]
        y = coords[:, 1]
        z = values
        
        lista_modelo = ["spherical", "exponential", "gaussian", "linear", "power"]
        nlags = 20
        resumen = []
        best_rmse = float('inf')
        best_modelo = None
        
        if var_json_path and os.path.exists(var_json_path):
            feedback.pushInfo("Usando parámetros de Variograma proporcionados en JSON...")
            try:
                with open(var_json_path, 'r') as f:
                    params_dict = json.load(f)
                best_modelo = params_dict.get('model_type', 'spherical')
                nlags = params_dict.get('nlags', 20)
                variogram_parameters = params_dict.get('parameters', None)
                
                feedback.pushInfo("Ajustando modelo Kriging Ordinario con parámetros importados...")
                ok_final = OrdinaryKriging(x, y, z, variogram_model=best_modelo, nlags=nlags,
                                           variogram_parameters=variogram_parameters,
                                           verbose=False, enable_plotting=False)
            except Exception as e:
                raise QgsProcessingException(f"Error al cargar JSON de variograma o ajustar modelo: {str(e)}")
            
            res_df = pd.DataFrame([{"Modelo": best_modelo, "Nota": "Importado de JSON"}])
            csv_path = os.path.join(output_dir, 'validacion_kriging.csv')
            res_df.to_csv(csv_path, index=False)
            
        else:
            step = 0
            total_steps = len(lista_modelo)
            feedback.pushInfo("JSON no proporcionado. Iniciando validación cruzada (LOOCV) para determinar el mejor modelo...")
    
            # 2. Análisis de validación
            for modulo in lista_modelo:
                if feedback.isCanceled():
                    return {}
                
                y_true, y_pred, var_krig = [], [], []
                for i in range(n):
                    puntos_x  = np.delete(x , i, axis=0)
                    puntos_y  = np.delete(y , i, axis=0)
                    valores_z = np.delete(z, i)
                    try:
                        ok = OrdinaryKriging(puntos_x, puntos_y, valores_z,
                                             variogram_model=modulo, nlags=nlags,
                                             verbose=False, enable_plotting=False)
                        zhat, ss = ok.execute("points", np.array([x[i]]), np.array([y[i]]))
                        zhat, ss = float(zhat[0]), float(ss[0])
                    except Exception as e:
                        # En caso de error de algebra lineal
                        zhat, ss = np.mean(valores_z), 0.0
                        
                    y_true.append(z[i])
                    y_pred.append(zhat)
                    var_krig.append(ss)
                    
                y_true = np.array(y_true)
                y_pred = np.array(y_pred)
                e = y_true - y_pred
                me   = float(np.nanmean(e))
                mae  = float(np.nanmean(np.abs(e)))
                rmse = float(np.sqrt(np.nanmean(e**2)))
                ss_res = np.nansum((e)**2)
                ss_tot = np.nansum((y_true - np.nanmean(y_true))**2)
                r2   = float(1 - (ss_res / ss_tot)) if ss_tot != 0 else 0.0
                eficiencia = r2 * 100.0
                
                val_safe = np.where(y_true == 0, 1e-12, y_true)
                mpe = float(100 * np.nanmean(e / val_safe))
                mape = float(100 * np.nanmean(np.abs(e / val_safe)))
                
                resumen.append({
                    "Modelo": modulo, 
                    "RMSE": round(rmse, 4), 
                    "MAE": round(mae, 4), 
                    "ME (Bias)": round(me, 4), 
                    "MPE (%)": round(mpe, 4),
                    "MAPE (%)": round(mape, 4),
                    "R²": round(r2, 4),
                    "Eficiencia (%)": round(eficiencia, 4)
                })
                
                if rmse < best_rmse:
                    best_rmse = rmse
                    best_modelo = modulo
                    
                step += 1
                feedback.setProgress(int((step / total_steps) * 30))
    
            res_df = pd.DataFrame(resumen).sort_values("RMSE").reset_index(drop=True)
            csv_path = os.path.join(output_dir, 'validacion_kriging.csv')
            res_df.to_csv(csv_path, index=False)
            feedback.pushInfo(f"Resultados de validación cruzada guardados en: {csv_path}")
            feedback.pushInfo(f"Mejor Modelo es: {best_modelo}")
    
            # 3. Calcular Kriging final y semivarianza para gráficos
            feedback.pushInfo("Ajustando modelo Kriging con todos los datos...")
            try:
                ok_final = OrdinaryKriging(x, y, z, variogram_model=best_modelo, nlags=nlags,
                                           verbose=False, enable_plotting=False)
            except Exception as e:
                raise QgsProcessingException(f"Error al ajustar Kriging Ordinario: {str(e)}")

        # Gráfico del semivariograma usando matplotlib
        feedback.pushInfo("Generando gráfico del semivariograma...")
        plot_path = os.path.join(output_dir, 'semivariograma.png')
        
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.plot(ok_final.lags, ok_final.semivariance, 'bo', label='Semivarianza experimental')
        # Calcular la teórica para la línea
        x_lag = np.linspace(0, max(ok_final.lags), 100)
        y_theo = ok_final.variogram_function(ok_final.variogram_model_parameters, x_lag)
        ax.plot(x_lag, y_theo, 'r-', label=f'Modelo teórico ({best_modelo})')
        
        ax.set_title("Semivariograma Experimental vs Teórico")
        ax.set_xlabel("Distancia (Lag)")
        ax.set_ylabel("Semivarianza")
        ax.legend()
        ax.grid(True, linestyle='--', alpha=0.6)
        plt.tight_layout()
        plt.savefig(plot_path, dpi=150)
        plt.close(fig)

        # 4. Generar Raster con execute('grid')
        feedback.pushInfo("Calculando grid interpolado...")
        cols = int(np.ceil((xmax - xmin) / cell_size))
        rows = int(np.ceil((ymax - ymin) / cell_size))
        
        xmax = xmin + cols * cell_size
        ymin = ymax - rows * cell_size
        
        x_centers = np.linspace(xmin + cell_size/2, xmax - cell_size/2, cols)
        y_centers = np.linspace(ymax - cell_size/2, ymin + cell_size/2, rows)
        
        # pykrige ok.execute('grid', x, y) returns z, ss arrays of shape (len(y), len(x))
        # Note: y must be 1D, x must be 1D
        z_grid, ss_grid = ok_final.execute("grid", x_centers, y_centers)
        
        raster_path = os.path.join(output_dir, 'raster_kriging_final.tif')
        driver = gdal.GetDriverByName('GTiff')
        out_raster = driver.Create(raster_path, cols, rows, 1, gdal.GDT_Float32)
        out_raster.SetGeoTransform((xmin, cell_size, 0, ymax, 0, -cell_size))
        
        crs = layer.crs()
        srs = osr.SpatialReference()
        srs.ImportFromWkt(crs.toWkt())
        out_raster.SetProjection(srs.ExportToWkt())
        
        band = out_raster.GetRasterBand(1)
        # Check orientation: QGIS expects [rows, cols] from Top-Left to Bottom-Right
        # ok.execute('grid', x_centers, y_centers) computes for y[0] to y[-1]
        # In our case y_centers goes from Top (ymax) to Bottom (ymin), so it matches
        band.WriteArray(z_grid.data)
        band.SetNoDataValue(-9999)
        band.FlushCache()
        out_raster = None
        
        feedback.setProgress(85)
        
        # Opcional: Generar raster de varianza de kriging
        var_raster_path = os.path.join(output_dir, 'raster_kriging_varianza.tif')
        out_var_raster = driver.Create(var_raster_path, cols, rows, 1, gdal.GDT_Float32)
        out_var_raster.SetGeoTransform((xmin, cell_size, 0, ymax, 0, -cell_size))
        out_var_raster.SetProjection(srs.ExportToWkt())
        var_band = out_var_raster.GetRasterBand(1)
        var_band.WriteArray(ss_grid.data)
        var_band.SetNoDataValue(-9999)
        var_band.FlushCache()
        out_var_raster = None
        
        feedback.pushInfo(f"Rasters generados exitosamente.")

        # 5. Generar HTML Report
        feedback.pushInfo("Generando reporte HTML...")
        html_path = os.path.join(output_dir, 'reporte_kriging.html')
        
        table_html = ""
        if len(res_df) > 1:
            for i, row in res_df.iterrows():
                highlight = 'class="highlight"' if i == 0 else ""
                table_html += f"<tr {highlight}><td>{row['Modelo']}</td><td>{row['RMSE']}</td><td>{row['MAE']}</td><td>{row['ME (Bias)']}</td><td>{row['MPE (%)']}</td><td>{row['MAPE (%)']}</td><td>{row['R²']}</td><td>{row['Eficiencia (%)']}</td></tr>\n"
            table_section = f"""
            <h2>Comparación de Modelos Teóricos (Ordenados por RMSE)</h2>
            <table>
                <tr>
                    <th>Modelo Variograma</th>
                    <th>RMSE</th>
                    <th>MAE</th>
                    <th>ME (Bias)</th>
                    <th>MPE (%)</th>
                    <th>MAPE (%)</th>
                    <th>R²</th>
                    <th>Eficiencia (%)</th>
                </tr>
                {table_html}
            </table>
            """
        else:
            table_section = f"<p><em>Modelo {best_modelo} importado directamente de JSON sin validación cruzada en este paso.</em></p>"
            
        html_content = f"""
        <!DOCTYPE html>
        <html lang="es">
        <head>
            <meta charset="UTF-8">
            <title>Reporte de Interpolación Kriging</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; color: #333; }}
                h1, h2, h3 {{ color: #2c3e50; }}
                table {{ border-collapse: collapse; width: 95%; margin-top: 20px; font-size: 0.9em; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: center; }}
                th {{ background-color: #34495e; color: white; }}
                tr:nth-child(even) {{ background-color: #f2f2f2; }}
                .highlight {{ background-color: #d4edda; font-weight: bold; }}
                .interpretacion {{ background-color: #e8f4f8; padding: 15px; border-left: 5px solid #3498db; margin-top: 20px; }}
                .grafico {{ text-align: center; margin-top: 20px; }}
                img {{ max-width: 800px; height: auto; border: 1px solid #ccc; box-shadow: 2px 2px 5px rgba(0,0,0,0.1); }}
            </style>
        </head>
        <body>
            <h1>Resultados de Interpolación Kriging Ordinario</h1>
            
            <div class="interpretacion">
                <h2>Mejor Modelo de Semivariograma: {best_modelo}</h2>
                <p>El algoritmo de Kriging ha evaluado los modelos teóricos, determinando que <strong>{best_modelo}</strong> minimiza el Error Cuadrático Medio (RMSE) durante la validación cruzada Leave-One-Out.</p>
                <p><strong>Parámetros Ajustados del Variograma Teórico:</strong></p>
                <ul>
                    <li>Sill (Meseta): {ok_final.variogram_model_parameters[0]:.4f}</li>
                    <li>Range (Rango): {ok_final.variogram_model_parameters[1]:.4f}</li>
                    <li>Nugget (Efecto Pepita): {ok_final.variogram_model_parameters[2]:.4f}</li>
                </ul>
            </div>
            
            <div class="grafico">
                <h2>Semivariograma (Experimental y Teórico)</h2>
                <img src="file:///{plot_path.replace(os.sep, '/')}" alt="Semivariograma">
            </div>

            {table_section}
        </body>
        </html>
        """
        
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
            
        feedback.pushInfo(f"Reporte HTML generado en: {html_path}")
        feedback.setProgress(100)

        return {
            'OUTPUT_CSV': csv_path,
            'OUTPUT_HTML': html_path,
            'OUTPUT_RASTER': raster_path,
            'OUTPUT_VAR_RASTER': var_raster_path
        }
