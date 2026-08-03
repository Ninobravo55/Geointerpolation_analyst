import os
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from qgis.core import (QgsProcessing, QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterField,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterFolderDestination,
                       QgsProcessingException)

try:
    from pykrige.ok import OrdinaryKriging
except ImportError:
    OrdinaryKriging = None

class KrigingVariogramAlgorithm(QgsProcessingAlgorithm):
    """
    Herramienta 2: Análisis de Variograma
    """
    INPUT = 'INPUT'
    FIELD = 'FIELD'
    NLAGS = 'NLAGS'
    OUTPUT_DIR = 'OUTPUT_DIR'

    def tr(self, string):
        from qgis.PyQt.QtCore import QCoreApplication
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return KrigingVariogramAlgorithm()

    def name(self):
        return 'kriging_variogram'

    def displayName(self):
        return self.tr('2. Análisis de Variograma')

    def group(self):
        return self.tr('Interpolación')

    def groupId(self):
        return 'interpolacion'

    def shortHelpString(self):
        return self.tr("Evalúa distintos modelos teóricos de variograma mediante validación cruzada y genera los parámetros óptimos para Kriging.")

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                self.tr('Capa vectorial de puntos'),
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
            QgsProcessingParameterNumber(
                self.NLAGS,
                self.tr('Número de rezagos (Lags)'),
                QgsProcessingParameterNumber.Integer,
                20, False, 5, 200
            )
        )
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_DIR,
                self.tr('Carpeta de salida para resultados')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        if OrdinaryKriging is None:
            raise QgsProcessingException("La librería 'pykrige' no está instalada. Usa la opción 'Instalar Dependencias' en el menú del plugin.")

        source = self.parameterAsSource(parameters, self.INPUT, context)
        field_name = self.parameterAsString(parameters, self.FIELD, context)
        nlags = self.parameterAsInt(parameters, self.NLAGS, context)
        output_dir = self.parameterAsString(parameters, self.OUTPUT_DIR, context)

        if source is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # Extraer puntos
        field_index = source.fields().lookupField(field_name)
        features = list(source.getFeatures())
        
        n = len(features)
        if n < 10:
            raise QgsProcessingException("No hay suficientes puntos para el Variograma (mínimo 10).")
            
        coords = np.zeros((n, 2))
        values = np.zeros(n)
        
        for i, feat in enumerate(features):
            geom = feat.geometry()
            pt = geom.asPoint()
            coords[i, 0] = pt.x()
            coords[i, 1] = pt.y()
            values[i] = float(feat.attributes()[field_index])

        x = coords[:, 0]
        y = coords[:, 1]
        z = values

        lista_modelo = ["spherical", "exponential", "gaussian", "linear", "power"]
        resumen = []
        best_rmse = float('inf')
        best_modelo = None
        
        step = 0
        total_steps = len(lista_modelo)
        feedback.pushInfo("Evaluando modelos teóricos mediante Validación Cruzada Leave-One-Out...")

        for modulo in lista_modelo:
            if feedback.isCanceled():
                return {}
            
            y_true, y_pred = [], []
            for i in range(n):
                puntos_x  = np.delete(x , i, axis=0)
                puntos_y  = np.delete(y , i, axis=0)
                valores_z = np.delete(z, i)
                try:
                    ok = OrdinaryKriging(puntos_x, puntos_y, valores_z,
                                         variogram_model=modulo, nlags=nlags,
                                         verbose=False, enable_plotting=False)
                    zhat, ss = ok.execute("points", np.array([x[i]]), np.array([y[i]]))
                    zhat = float(zhat[0])
                except Exception:
                    zhat = np.mean(valores_z)
                    
                y_true.append(z[i])
                y_pred.append(zhat)
                
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
            feedback.setProgress(int((step / total_steps) * 80))

        # Guardar tabla comparativa
        res_df = pd.DataFrame(resumen).sort_values("RMSE").reset_index(drop=True)
        csv_path = os.path.join(output_dir, 'modelos_variograma.csv')
        res_df.to_csv(csv_path, index=False)
        feedback.pushInfo(f"Mejor Modelo es: {best_modelo} (RMSE: {best_rmse})")

        # 3. Generar Semivariograma
        feedback.pushInfo("Generando semivariograma del mejor modelo...")
        try:
            ok_final = OrdinaryKriging(x, y, z, variogram_model=best_modelo, nlags=nlags,
                                       verbose=False, enable_plotting=False)
        except Exception as e:
            raise QgsProcessingException(f"Error al ajustar Variograma: {str(e)}")

        plot_path = os.path.join(output_dir, 'semivariograma_teorico.png')
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.plot(ok_final.lags, ok_final.semivariance, 'bo', label='Semivarianza experimental')
        
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

        # 4. Exportar JSON de parámetros
        json_path = os.path.join(output_dir, 'parametros_variograma.json')
        params_dict = {
            "model_type": best_modelo,
            "nlags": nlags,
            "parameters": [float(p) for p in ok_final.variogram_model_parameters]
        }
        with open(json_path, 'w') as f:
            json.dump(params_dict, f, indent=4)

        # Generar Reporte HTML
        html_path = os.path.join(output_dir, 'reporte_variograma.html')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(f'''
            <html>
            <head>
                <title>Análisis de Variograma</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 40px; color: #333; }}
                    h1, h2 {{ color: #2c3e50; }}
                    .container {{ max-width: 900px; margin: auto; }}
                    table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
                    th, td {{ padding: 10px; border: 1px solid #ddd; text-align: left; }}
                    th {{ background-color: #f4f4f4; }}
                    .highlight {{ font-weight: bold; color: #d35400; }}
                    .img-container {{ text-align: center; margin: 20px 0; }}
                    img {{ max-width: 100%; border: 1px solid #ccc; padding: 5px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>Análisis de Variograma Kriging</h1>
                    <p><strong>Mejor Modelo Teórico:</strong> <span class="highlight">{best_modelo}</span></p>
                    <p><strong>Lags evaluados:</strong> {nlags}</p>
                    <p><em>Este modelo fue seleccionado automáticamente utilizando Validación Cruzada Leave-One-Out.</em></p>
                    
                    <div class="img-container">
                        <h3>Semivariograma Ajustado</h3>
                        <img src="semivariograma_teorico.png" alt="Semivariograma">
                    </div>
                    
                    <h2>Comparación de Modelos</h2>
                    {res_df.to_html(classes="table", index=False)}
                    
                    <p>Los parámetros óptimos han sido exportados al archivo <code>parametros_variograma.json</code> para su uso en la herramienta de Kriging Ordinario.</p>
                </div>
            </body>
            </html>
            ''')
            
        feedback.pushInfo("Análisis de variograma completado exitosamente.")
        return {'OUTPUT_DIR': output_dir}
