import os
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterExtent,
    QgsProcessingParameterFolderDestination,
    QgsFeature,
    QgsVectorLayer,
    QgsField,
    QgsVectorFileWriter,
    QgsCoordinateReferenceSystem,
)

class IdwLoocvAlgorithm(QgsProcessingAlgorithm):
    INPUT = 'INPUT'
    FIELD = 'FIELD'
    CELL_SIZE = 'CELL_SIZE'
    EXTENT = 'EXTENT'
    OUTPUT_DIR = 'OUTPUT_DIR'
    HTML_REPORT = 'HTML_REPORT'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return IdwLoocvAlgorithm()

    def name(self):
        return 'idw_loocv'

    def displayName(self):
        return self.tr('Interpolación IDW con LOOCV')

    def group(self):
        return self.tr('Interpolación')

    def groupId(self):
        return 'interpolacion'

    def shortHelpString(self):
        return self.tr(
            "Esta herramienta realiza interpolación IDW buscando los mejores parámetros "
            "(Power y Neighbors) mediante validación cruzada Leave-One-Out (LOOCV). "
            "Calcula RMSE, MAE, ME, R² y Bias, y genera gráficos y un raster con "
            "la mejor configuración encontrada."
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
                self.tr('Campo de la variable'), 
                None, 
                self.INPUT, 
                QgsProcessingParameterField.Numeric
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.CELL_SIZE, 
                self.tr('Tamaño de píxel del raster a generar'), 
                QgsProcessingParameterNumber.Double, 
                100.0, 
                False, 
                0.0001
            )
        )
        self.addParameter(
            QgsProcessingParameterExtent(
                self.EXTENT, 
                self.tr('Extensión de salida del raster')
            )
        )
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_DIR, 
                self.tr('Directorio de salida para los resultados')
            )
        )
        from qgis.core import QgsProcessingOutputHtml
        self.addOutput(
            QgsProcessingOutputHtml(
                self.HTML_REPORT,
                self.tr('Reporte HTML de Resultados')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        try:
            import numpy as np
            import pandas as pd
            from scipy.spatial import cKDTree
            import matplotlib.pyplot as plt
            import seaborn as sns
            from osgeo import gdal, osr
        except ImportError as e:
            raise QgsProcessingException(f"Error: Faltan dependencias necesarias: {e}. Instale numpy, pandas, scipy, matplotlib y seaborn en su entorno de QGIS.")

        source = self.parameterAsSource(parameters, self.INPUT, context)
        field_name = self.parameterAsString(parameters, self.FIELD, context)
        cell_size = self.parameterAsDouble(parameters, self.CELL_SIZE, context)
        extent = self.parameterAsExtent(parameters, self.EXTENT, context)
        output_dir = self.parameterAsString(parameters, self.OUTPUT_DIR, context)

        if source is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))
            
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # 1. Leer puntos y valores
        coords = []
        values = []
        features = []
        
        field_idx = source.fields().lookupField(field_name)
        
        for feat in source.getFeatures():
            geom = feat.geometry()
            if geom.isNull(): 
                continue
            point = geom.asPoint()
            val = feat.attribute(field_idx)
            if val is None: 
                continue
            
            coords.append([point.x(), point.y()])
            values.append(float(val))
            features.append(feat)
            
        coords = np.array(coords)
        values = np.array(values)
        
        if len(coords) < 10:
            raise QgsProcessingException("No hay suficientes puntos para hacer LOOCV (mínimo 10).")
            
        # 2. Definir grilla de parámetros
        powers = np.arange(1.0, 6.0, 0.5)
        raw_neighbors = [3, 5, 8, 10, 15, 20, 25, 30]
        neighbors_list = [n for n in raw_neighbors if n < len(coords)]
        if not neighbors_list:
            neighbors_list = [len(coords) - 1]
            
        # KDTree para búsqueda de vecinos
        tree = cKDTree(coords)
        
        # Etapa 1: Encontrar el mejor Power usando todos los puntos (hasta un máximo de 500 para rendimiento)
        feedback.pushInfo("Etapa 1: Optimizando Power (LOOCV)...")
        best_power_rmse = float('inf')
        best_power = 2.0
        
        max_k = min(len(coords), 500)
        distances, indices = tree.query(coords, k=max_k)
        
        for p in powers:
            if feedback.isCanceled():
                return {}
            
            predicted = np.zeros(len(coords))
            for i in range(len(coords)):
                dists = distances[i][1:]
                idxs = indices[i][1:]
                dists[dists == 0] = 1e-12
                
                weights = 1.0 / (dists ** p)
                pred_val = np.sum(weights * values[idxs]) / np.sum(weights)
                predicted[i] = pred_val
                
            rmse = np.sqrt(np.mean((values - predicted)**2))
            if rmse < best_power_rmse:
                best_power_rmse = rmse
                best_power = p
                
        feedback.pushInfo(f"Mejor Power encontrado: {best_power} (RMSE: {best_power_rmse:.4f})")
        
        # Etapa 2: Optimizar Neighbors usando el best_power
        feedback.pushInfo("Etapa 2: Optimizando Neighbors (LOOCV)...")
        results = []
        best_rmse = float('inf')
        best_params = None
        best_residuals = None
        best_predicted = None
        
        step = 0
        total_steps = len(neighbors_list)
        
        for n in neighbors_list:
            if feedback.isCanceled():
                return {}
            
            predicted = np.zeros(len(coords))
            for i in range(len(coords)):
                dists = distances[i][1:n+1]
                idxs = indices[i][1:n+1]
                dists[dists == 0] = 1e-12
                
                weights = 1.0 / (dists ** best_power)
                pred_val = np.sum(weights * values[idxs]) / np.sum(weights)
                predicted[i] = pred_val
                
            residuals = values - predicted
            rmse = float(np.sqrt(np.mean(residuals**2)))
            mae = float(np.mean(np.abs(residuals)))
            me = float(np.mean(residuals))
            
            # MPE y MAPE
            val_safe = np.where(values == 0, 1e-12, values)
            mpe = float(100 * np.mean(residuals / val_safe))
            mape = float(100 * np.mean(np.abs(residuals / val_safe)))
            
            # R2 y Eficiencia
            ss_res = np.sum(residuals**2)
            ss_tot = np.sum((values - np.mean(values))**2)
            r2 = float(1 - (ss_res / ss_tot)) if ss_tot != 0 else 0.0
            eficiencia = r2 * 100.0
            
            results.append({
                'Power': best_power,
                'Neighbors': n,
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
                    'Power': best_power, 
                    'Neighbors': n, 
                    'RMSE': rmse, 
                    'MAE': mae, 
                    'ME': me, 
                    'MPE': mpe, 
                    'MAPE': mape, 
                    'R2': r2, 
                    'Eficiencia': eficiencia
                }
                best_residuals = residuals
                best_predicted = predicted
                
            step += 1
            feedback.setProgress(int(step * 40 / total_steps))
                
        # Mostrar tabla de resultados
        results_df = pd.DataFrame(results)
        results_df.sort_values('RMSE', inplace=True)
        results_csv_path = os.path.join(output_dir, 'loocv_results.csv')
        results_df.to_csv(results_csv_path, index=False)
        feedback.pushInfo(f"Resultados guardados en: {results_csv_path}")
        feedback.pushInfo(f"Mejor combinación: Power={best_params['Power']}, Neighbors={best_params['Neighbors']}, RMSE={best_rmse:.4f}")
        
        # 3. Crear gráficos para la mejor combinación
        feedback.pushInfo("Generando gráficos...")
        plt.style.use('seaborn-v0_8-whitegrid')
        
        # Gráfico Scatter Observado vs Predicho
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.scatter(values, best_predicted, alpha=0.7, edgecolors='k')
        min_val = min(values.min(), best_predicted.min())
        max_val = max(values.max(), best_predicted.max())
        ax.plot([min_val, max_val], [min_val, max_val], 'r--', lw=2)
        ax.set_xlabel('Valores Observados')
        ax.set_ylabel('Valores Predichos (IDW)')
        ax.set_title(f"LOOCV IDW (P={best_params['Power']}, N={best_params['Neighbors']})\n$R^2$={best_params['R2']:.3f}, RMSE={best_rmse:.3f}")
        scatter_path = os.path.join(output_dir, 'loocv_scatter.png')
        plt.tight_layout()
        plt.savefig(scatter_path, dpi=300)
        plt.close(fig)
        
        # Histograma de Residuos
        fig, ax = plt.subplots(figsize=(6, 4))
        sns.histplot(best_residuals, kde=True, ax=ax)
        ax.axvline(0, color='r', linestyle='--')
        ax.set_xlabel('Residuos (Observado - Predicho)')
        ax.set_ylabel('Frecuencia')
        ax.set_title(f"Distribución de Residuos\nBias (ME): {best_params['ME']:.4f}")
        hist_path = os.path.join(output_dir, 'loocv_residuals_hist.png')
        plt.tight_layout()
        plt.savefig(hist_path, dpi=300)
        plt.close(fig)
        
        feedback.setProgress(50)
        
        # 4. Generar Capa de Residuos
        feedback.pushInfo("Generando capa de residuos...")
        crs = source.sourceCrs()
        res_layer = QgsVectorLayer(f"Point?crs={crs.authid()}", "Residuos_IDW", "memory")
        res_provider = res_layer.dataProvider()
        
        # Añadir campos
        new_fields = source.fields().toList()
        new_fields.append(QgsField("Predicho", QVariant.Double))
        new_fields.append(QgsField("Residuo", QVariant.Double))
        res_provider.addAttributes(new_fields)
        res_layer.updateFields()
        
        res_features = []
        for i, feat in enumerate(features):
            new_feat = QgsFeature(res_layer.fields())
            new_feat.setGeometry(feat.geometry())
            attrs = feat.attributes()
            attrs.append(float(best_predicted[i]))
            attrs.append(float(best_residuals[i]))
            new_feat.setAttributes(attrs)
            res_features.append(new_feat)
            
        res_provider.addFeatures(res_features)
        res_layer_path = os.path.join(output_dir, 'capa_residuos.gpkg')
        QgsVectorFileWriter.writeAsVectorFormatV3(res_layer, res_layer_path, res_layer.transformContext(), QgsVectorFileWriter.SaveVectorOptions())
        
        feedback.setProgress(60)
        
        # 5. Generar Raster IDW con GDAL/NumPy usando los mejores parámetros
        feedback.pushInfo("Generando raster IDW final...")
        
        xmin = extent.xMinimum()
        xmax = extent.xMaximum()
        ymin = extent.yMinimum()
        ymax = extent.yMaximum()
        
        cols = int(np.ceil((xmax - xmin) / cell_size))
        rows = int(np.ceil((ymax - ymin) / cell_size))
        
        # Ajustar extent si es necesario
        xmax = xmin + cols * cell_size
        ymin = ymax - rows * cell_size
        
        x_centers = np.linspace(xmin + cell_size/2, xmax - cell_size/2, cols)
        y_centers = np.linspace(ymax - cell_size/2, ymin + cell_size/2, rows)
        grid_x, grid_y = np.meshgrid(x_centers, y_centers)
        
        grid_coords = np.vstack([grid_x.ravel(), grid_y.ravel()]).T
        
        best_p = best_params['Power']
        best_n = best_params['Neighbors']
        
        # Predicción en lotes para no saturar memoria
        batch_size = 100000
        grid_z = np.zeros(grid_coords.shape[0])
        
        for i in range(0, grid_coords.shape[0], batch_size):
            if feedback.isCanceled():
                return {}
            batch = grid_coords[i:i+batch_size]
            dists, idxs = tree.query(batch, k=best_n)
            
            # Reemplazar 0 dists (si el punto coincide exactamente)
            exact_match = (dists == 0)
            dists[exact_match] = 1e-10
            
            weights = 1.0 / (dists ** best_p)
            vals = values[idxs]
            
            pred = np.sum(weights * vals, axis=1) / np.sum(weights, axis=1)
            
            # Si hubo un match exacto, usamos ese valor
            for j in range(len(batch)):
                if np.any(exact_match[j]):
                    match_idx = np.where(exact_match[j])[0][0]
                    pred[j] = vals[j, match_idx]
                    
            grid_z[i:i+batch_size] = pred
            
            progress = 60 + int( (i / grid_coords.shape[0]) * 35 )
            feedback.setProgress(progress)
            
        grid_z = grid_z.reshape((rows, cols))
        
        raster_path = os.path.join(output_dir, 'raster_idw_final.tif')
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
        
        out_raster = None # Cerrar
        
        feedback.pushInfo(f"Raster generado exitosamente: {raster_path}")
        feedback.setProgress(100)
        
        # 6. Generar Reporte HTML
        feedback.pushInfo("Generando reporte HTML...")
        html_path = os.path.join(output_dir, 'reporte_loocv.html')
        
        table_html = ""
        for i, row in results_df.head(10).iterrows():
            table_html += f"<tr><td>{row['Power']}</td><td>{row['Neighbors']}</td><td>{row['RMSE']}</td><td>{row['MAE']}</td><td>{row['ME (Bias)']}</td><td>{row['MPE (%)']}</td><td>{row['MAPE (%)']}</td><td>{row['R²']}</td><td>{row['Eficiencia (%)']}</td></tr>\n"
            
        html_content = f"""
        <!DOCTYPE html>
        <html lang="es">
        <head>
            <meta charset="UTF-8">
            <title>Reporte de Interpolación IDW - LOOCV</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; color: #333; }}
                h1, h2, h3 {{ color: #2c3e50; }}
                table {{ border-collapse: collapse; width: 95%; margin-top: 20px; font-size: 0.9em; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: center; }}
                th {{ background-color: #34495e; color: white; }}
                tr:nth-child(even) {{ background-color: #f2f2f2; }}
                .highlight {{ background-color: #d4edda; font-weight: bold; }}
                .interpretacion {{ background-color: #e8f4f8; padding: 15px; border-left: 5px solid #3498db; margin-top: 20px; }}
                .img-container {{ display: flex; gap: 20px; margin-top: 20px; }}
                .img-container img {{ max-width: 45%; border: 1px solid #ccc; box-shadow: 2px 2px 5px rgba(0,0,0,0.1); }}
            </style>
        </head>
        <body>
            <h1>Resultados de Validación Cruzada (LOOCV) para Interpolación IDW</h1>
            
            <div class="interpretacion">
                <h2>Interpretación del Mejor Modelo</h2>
                <p>El mejor modelo de interpolación IDW encontrado corresponde a:</p>
                <ul>
                    <li><strong>Power (Potencia):</strong> {best_params['Power']}</li>
                    <li><strong>Neighbors (Vecinos):</strong> {best_params['Neighbors']}</li>
                </ul>
                <p>Las métricas de error para este modelo son:</p>
                <ul>
                    <li><strong>RMSE (Error Cuadrático Medio):</strong> {best_rmse:.4f}. Representa la magnitud promedio del error en las mismas unidades de la variable. Un valor más cercano a 0 indica un mejor ajuste.</li>
                    <li><strong>MAE (Error Absoluto Medio):</strong> {best_params['MAE']:.4f}. Es el promedio absoluto de los errores, menos sensible a valores atípicos que el RMSE.</li>
                    <li><strong>R² (Coeficiente de Determinación):</strong> {best_params['R2']:.4f}. Indica que el {best_params['R2']*100:.2f}% de la varianza de los datos es explicada por el modelo IDW.</li>
                    <li><strong>Eficiencia (%):</strong> {best_params['Eficiencia']:.4f}%. Indica la eficiencia y ajuste general de la interpolación (basado en el R²).</li>
                    <li><strong>Bias / ME (Error Medio):</strong> {best_params['ME']:.4f}. Un valor cercano a 0 indica que el modelo no tiene una tendencia sistemática a sobreestimar o subestimar los valores.</li>
                    <li><strong>MPE (%) (Porcentaje de Error Medio):</strong> {best_params['MPE']:.4f}%. Indica el sesgo promedio en porcentaje.</li>
                    <li><strong>MAPE (%) (Porcentaje de Error Absoluto Medio):</strong> {best_params['MAPE']:.4f}%. Mide la precisión promedio del modelo en términos porcentuales absolutos.</li>
                </ul>
            </div>

            <h2>Top 10 Mejores Configuraciones (Ordenadas por RMSE)</h2>
            <table>
                <tr>
                    <th>Power</th>
                    <th>Neighbors</th>
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


            <h2>Gráficos de Diagnóstico</h2>
            <div class="img-container">
                <img src="loocv_scatter.png" alt="Observado vs Predicho">
                <img src="loocv_residuals_hist.png" alt="Histograma de Residuos">
            </div>
            
            <div class="interpretacion">
                <h3>Interpretación de los Gráficos</h3>
                <p><strong>Observado vs Predicho:</strong> La línea roja punteada representa un ajuste perfecto (donde el valor observado es igual al predicho). Si los puntos están muy dispersos lejos de la línea, significa que hay mayor error de estimación. El IDW suele tener un efecto de "suavizado", subestimando valores altos y sobreestimando valores bajos.</p>
                <p><strong>Histograma de Residuos:</strong> Muestra la distribución del error. Lo ideal es una curva simétrica centrada en cero (línea roja), lo que indicaría que los errores se distribuyen de manera normal y no hay sesgo (bias) fuerte hacia un solo lado.</p>
            </div>
        </body>
        </html>
        """
        
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
            
        feedback.pushInfo(f"Reporte HTML generado: {{html_path}}")

        return {
            'RASTER_IDW': raster_path,
            'RESIDUALS_LAYER': res_layer_path,
            'CSV_RESULTS': results_csv_path,
            'HTML_REPORT': html_path
        }
