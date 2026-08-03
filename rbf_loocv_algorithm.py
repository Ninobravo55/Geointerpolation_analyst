import os
import numpy as np
import pandas as pd
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterField,
                       QgsProcessingParameterExtent,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterFolderDestination,
                       QgsProcessingException,
                       QgsVectorLayer,
                       QgsVectorFileWriter,
                       QgsFeature,
                       QgsField)
from osgeo import gdal, osr
from scipy.interpolate import RBFInterpolator

class RbfLoocvAlgorithm(QgsProcessingAlgorithm):
    INPUT = 'INPUT'
    FIELD = 'FIELD'
    EXTENT = 'EXTENT'
    CELLSIZE = 'CELLSIZE'
    OUTPUT_DIR = 'OUTPUT_DIR'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return RbfLoocvAlgorithm()

    def name(self):
        return 'rbf_loocv'

    def displayName(self):
        return self.tr('Interpolación Base Radial con LOOCV')

    def group(self):
        return self.tr('Interpolación')

    def groupId(self):
        return 'interpolacion'

    def shortHelpString(self):
        return self.tr(
            "Esta herramienta realiza interpolación Base Radial (RBF) buscando los mejores parámetros "
            "(Kernels, Smoothing y Epsilon) mediante validación cruzada Leave-One-Out (LOOCV). "
            "Calcula RMSE, MAE, ME, R² y otras métricas, y genera un raster con la mejor configuración."
        )

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
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_DIR,
                self.tr('Carpeta de salida para reportes y raster')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        # 1. Obtener parámetros
        source = self.parameterAsSource(parameters, self.INPUT, context)
        field_name = self.parameterAsString(parameters, self.FIELD, context)
        extent_geom = self.parameterAsExtent(parameters, self.EXTENT, context)
        cell_size = self.parameterAsDouble(parameters, self.CELLSIZE, context)
        output_dir = self.parameterAsString(parameters, self.OUTPUT_DIR, context)

        if source is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))

        xmin, xmax = extent_geom.xMinimum(), extent_geom.xMaximum()
        ymin, ymax = extent_geom.yMinimum(), extent_geom.yMaximum()

        # Extraer puntos
        field_index = source.fields().lookupField(field_name)
        features = list(source.getFeatures())
        coords = np.zeros((len(features), 2))
        values = np.zeros(len(features))
        for i, feat in enumerate(features):
            geom = feat.geometry()
            pt = geom.asPoint()
            coords[i, 0] = pt.x()
            coords[i, 1] = pt.y()
            values[i] = float(feat.attributes()[field_index])

        if len(coords) < 10:
            raise QgsProcessingException("No hay suficientes puntos para hacer LOOCV (mínimo 10).")

        # 2. Definir Grilla de parámetros RBF
        lista_kernels = ['linear', 'cubic', 'quintic', 'thin_plate_spline', 'multiquadric', 'inverse_multiquadric', 'gaussian']
        lista_smoothing = [0.0, 0.01, 0.1]
        lista_epsilon = [0.1, 1.0, 5.0]

        # 3. LOOCV
        results = []
        best_rmse = float('inf')
        best_params = None
        best_residuals = None
        best_predicted = None

        total_steps = len(lista_kernels) * len(lista_smoothing) * len(lista_epsilon)
        step = 0

        feedback.pushInfo(f"Iniciando LOOCV (Total combinaciones: {total_steps})...")

        for kernel in lista_kernels:
            for smoothing in lista_smoothing:
                for epsilon in lista_epsilon:
                    if feedback.isCanceled():
                        return {}
                    
                    residuals = np.zeros(len(coords))
                    predicted = np.zeros(len(coords))
                    
                    for i in range(len(coords)):
                        mask = np.ones(len(coords), dtype=bool)
                        mask[i] = False
                        
                        train_coords = coords[mask]
                        train_values = values[mask]
                        test_coord = coords[i:i+1] # Shape (1,2)
                        
                        try:
                            rbf = RBFInterpolator(train_coords, train_values, kernel=kernel, 
                                                  smoothing=smoothing, epsilon=epsilon)
                            z_pred = rbf(test_coord)[0]
                        except Exception as e:
                            z_pred = np.mean(train_values)
                            
                        predicted[i] = z_pred
                        residuals[i] = values[i] - z_pred

                    rmse = float(np.sqrt(np.mean(residuals**2)))
                    mae = float(np.mean(np.abs(residuals)))
                    me = float(np.mean(residuals))
                    
                    val_safe = np.where(values == 0, 1e-12, values)
                    mpe = float(100 * np.mean(residuals / val_safe))
                    mape = float(100 * np.mean(np.abs(residuals / val_safe)))
                    
                    ss_res = np.sum(residuals**2)
                    ss_tot = np.sum((values - np.mean(values))**2)
                    r2 = float(1 - (ss_res / ss_tot)) if ss_tot != 0 else 0.0
                    eficiencia = r2 * 100.0

                    results.append({
                        'Kernels': kernel,
                        'Smoothing': smoothing,
                        'Epsilon': epsilon,
                        'RMSE': round(rmse, 4),
                        'MAE': round(mae, 4),
                        'ME (Bias)': round(me, 4),
                        'MPE (%)': round(mpe, 4),
                        'MAPE (%)': round(mape, 4),
                        'R²': round(r2, 4),
                        'Eficiencia (%)': round(eficiencia, 4)
                    })

                    if rmse < best_rmse:
                        best_rmse = rmse
                        best_params = {
                            'Kernels': kernel, 
                            'Smoothing': smoothing, 
                            'Epsilon': epsilon,
                            'RMSE': rmse, 
                            'MAE': mae, 
                            'ME': me, 
                            'MPE': mpe, 
                            'MAPE': mape, 
                            'R2': r2, 
                            'Eficiencia': eficiencia
                        }
                        best_residuals = residuals.copy()
                        best_predicted = predicted.copy()
                        
                    step += 1
                    progress = int(step * 40 / total_steps)
                    feedback.setProgress(progress)

        results_df = pd.DataFrame(results)
        results_df.sort_values(by="RMSE", inplace=True)
        
        csv_path = os.path.join(output_dir, 'loocv_rbf_results.csv')
        results_df.to_csv(csv_path, index=False)
        feedback.pushInfo(f"Resultados de validación cruzada guardados en: {csv_path}")

        # Best interpolator
        feedback.pushInfo("Generando interpolador RBF con los mejores parámetros...")
        best_kernel = best_params['Kernels']
        best_smoothing = best_params['Smoothing']
        best_epsilon = best_params['Epsilon']
        
        final_rbf = RBFInterpolator(coords, values, kernel=best_kernel, 
                                    smoothing=best_smoothing, epsilon=best_epsilon)
        
        # 4. Generar Capa de Residuos
        feedback.pushInfo("Generando capa de residuos...")
        crs = source.sourceCrs()
        res_layer = QgsVectorLayer(f"Point?crs={crs.authid()}", "Residuos_RBF", "memory")
        res_provider = res_layer.dataProvider()
        
        new_fields = source.fields().toList()
        new_fields.append(QgsField("Predicho", QVariant.Double))
        new_fields.append(QgsField("Residuo", QVariant.Double))
        res_provider.addAttributes(new_fields)
        res_layer.updateFields()
        
        res_features = []
        for i, feat in enumerate(features):
            new_feat = QgsFeature(res_layer.fields())
            attrs = feat.attributes()
            attrs.append(float(best_predicted[i]))
            attrs.append(float(best_residuals[i]))
            new_feat.setAttributes(attrs)
            new_feat.setGeometry(feat.geometry())
            res_features.append(new_feat)
            
        res_provider.addFeatures(res_features)
        
        res_path = os.path.join(output_dir, 'residuos_rbf.gpkg')
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        QgsVectorFileWriter.writeAsVectorFormatV3(res_layer, res_path, context.transformContext(), options)
        
        # 5. Generar Raster con GDAL
        feedback.pushInfo("Calculando grid para RBF Raster...")
        cols = int(np.ceil((xmax - xmin) / cell_size))
        rows = int(np.ceil((ymax - ymin) / cell_size))
        
        xmax = xmin + cols * cell_size
        ymin = ymax - rows * cell_size
        
        x_centers = np.linspace(xmin + cell_size/2, xmax - cell_size/2, cols)
        y_centers = np.linspace(ymax - cell_size/2, ymin + cell_size/2, rows)
        grid_x, grid_y = np.meshgrid(x_centers, y_centers)
        grid_coords = np.vstack([grid_x.ravel(), grid_y.ravel()]).T
        
        feedback.pushInfo(f"El grid tiene {rows}x{cols} ({grid_coords.shape[0]} celdas).")
        
        batch_size = 50000
        grid_z = np.zeros(grid_coords.shape[0])
        
        for i in range(0, grid_coords.shape[0], batch_size):
            if feedback.isCanceled():
                return {}
            batch = grid_coords[i:i+batch_size]
            grid_z[i:i+batch_size] = final_rbf(batch)
            progress = 40 + int((i / grid_coords.shape[0]) * 40)
            feedback.setProgress(progress)
            
        grid_z = grid_z.reshape((rows, cols))
        
        raster_path = os.path.join(output_dir, 'raster_rbf_final.tif')
        driver = gdal.GetDriverByName('GTiff')
        out_raster = driver.Create(raster_path, cols, rows, 1, gdal.GDT_Float32)
        out_raster.SetGeoTransform((xmin, cell_size, 0, ymax, 0, -cell_size))
        
        srs = osr.SpatialReference()
        srs.ImportFromWkt(crs.toWkt())
        out_raster.SetProjection(srs.ExportToWkt())
        
        band = out_raster.GetRasterBand(1)
        band.WriteArray(grid_z)
        band.SetNoDataValue(-9999)
        band.FlushCache()
        out_raster = None
        
        feedback.pushInfo(f"Raster RBF generado exitosamente: {raster_path}")
        feedback.setProgress(90)
        
        # 6. Generar HTML Report
        feedback.pushInfo("Generando reporte HTML...")
        html_path = os.path.join(output_dir, 'reporte_loocv_rbf.html')
        
        table_html = ""
        for i, row in results_df.head(10).iterrows():
            table_html += f"<tr><td>{row['Kernels']}</td><td>{row['Smoothing']}</td><td>{row['Epsilon']}</td><td>{row['RMSE']}</td><td>{row['MAE']}</td><td>{row['ME (Bias)']}</td><td>{row['MPE (%)']}</td><td>{row['MAPE (%)']}</td><td>{row['R²']}</td><td>{row['Eficiencia (%)']}</td></tr>\n"
            
        html_content = f"""
        <!DOCTYPE html>
        <html lang="es">
        <head>
            <meta charset="UTF-8">
            <title>Reporte de Interpolación RBF - LOOCV</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; color: #333; }}
                h1, h2, h3 {{ color: #2c3e50; }}
                table {{ border-collapse: collapse; width: 95%; margin-top: 20px; font-size: 0.9em; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: center; }}
                th {{ background-color: #34495e; color: white; }}
                tr:nth-child(even) {{ background-color: #f2f2f2; }}
                .highlight {{ background-color: #d4edda; font-weight: bold; }}
                .interpretacion {{ background-color: #e8f4f8; padding: 15px; border-left: 5px solid #3498db; margin-top: 20px; }}
            </style>
        </head>
        <body>
            <h1>Resultados de Validación Cruzada (LOOCV) para Interpolación Base Radial (RBF)</h1>
            
            <div class="interpretacion">
                <h2>Interpretación del Mejor Modelo</h2>
                <p>El mejor modelo de interpolación RBF encontrado corresponde a:</p>
                <ul>
                    <li><strong>Kernel:</strong> {best_params['Kernels']}</li>
                    <li><strong>Smoothing:</strong> {best_params['Smoothing']}</li>
                    <li><strong>Epsilon:</strong> {best_params['Epsilon']}</li>
                </ul>
                <p>Las métricas de error para este modelo son:</p>
                <ul>
                    <li><strong>RMSE (Error Cuadrático Medio):</strong> {best_rmse:.4f}. Representa la magnitud promedio del error en las mismas unidades de la variable. Un valor más cercano a 0 indica un mejor ajuste.</li>
                    <li><strong>MAE (Error Absoluto Medio):</strong> {best_params['MAE']:.4f}. Es el promedio absoluto de los errores, menos sensible a valores atípicos que el RMSE.</li>
                    <li><strong>R² (Coeficiente de Determinación):</strong> {best_params['R2']:.4f}. Indica que el {best_params['R2']*100:.2f}% de la varianza de los datos es explicada por el modelo RBF.</li>
                    <li><strong>Eficiencia (%):</strong> {best_params['Eficiencia']:.4f}%. Indica la eficiencia y ajuste general de la interpolación.</li>
                    <li><strong>Bias / ME (Error Medio):</strong> {best_params['ME']:.4f}. Un valor cercano a 0 indica que el modelo no tiene una tendencia sistemática a sobreestimar o subestimar los valores.</li>
                    <li><strong>MPE (%) (Porcentaje de Error Medio):</strong> {best_params['MPE']:.4f}%. Indica el sesgo promedio en porcentaje.</li>
                    <li><strong>MAPE (%) (Porcentaje de Error Absoluto Medio):</strong> {best_params['MAPE']:.4f}%. Mide la precisión promedio del modelo en términos porcentuales absolutos.</li>
                </ul>
            </div>

            <h2>Top 10 Mejores Configuraciones (Ordenadas por RMSE)</h2>
            <table>
                <tr>
                    <th>Kernel</th>
                    <th>Smoothing</th>
                    <th>Epsilon</th>
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
            'OUTPUT_RESIDUALS': res_path
        }
