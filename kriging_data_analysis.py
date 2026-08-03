import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from itertools import combinations
from qgis.core import (QgsProcessing, QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterField,
                       QgsProcessingParameterFolderDestination,
                       QgsProcessingException)

class KrigingDataAnalysisAlgorithm(QgsProcessingAlgorithm):
    """
    Herramienta 1: Análisis Exploratorio de Datos Kriging
    """
    INPUT = 'INPUT'
    FIELD = 'FIELD'
    OUTPUT_DIR = 'OUTPUT_DIR'

    def tr(self, string):
        from qgis.PyQt.QtCore import QCoreApplication
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return KrigingDataAnalysisAlgorithm()

    def name(self):
        return 'kriging_data_analysis'

    def displayName(self):
        return self.tr('1. Análisis Exploratorio de Datos Kriging')

    def group(self):
        return self.tr('Interpolación')

    def groupId(self):
        return 'interpolacion'

    def shortHelpString(self):
        return self.tr("Realiza un análisis exploratorio de datos (estadísticas y nube de semivarianza) previo a la interpolación Kriging.")

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
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_DIR,
                self.tr('Carpeta de salida para reportes y gráficos')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        field_name = self.parameterAsString(parameters, self.FIELD, context)
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
            raise QgsProcessingException("Se requieren al menos 10 puntos para un análisis significativo.")
            
        coords = np.zeros((n, 2))
        values = np.zeros(n)
        
        for i, feat in enumerate(features):
            geom = feat.geometry()
            pt = geom.asPoint()
            coords[i, 0] = pt.x()
            coords[i, 1] = pt.y()
            values[i] = float(feat.attributes()[field_index])

        feedback.pushInfo(f"Analizando {n} puntos...")
        
        # 1. Estadística descriptiva
        df = pd.DataFrame({'X': coords[:, 0], 'Y': coords[:, 1], 'Z': values})
        stats = df['Z'].describe()
        stats['Asimetria'] = df['Z'].skew()
        stats['Curtosis'] = df['Z'].kurt()
        
        stats_path = os.path.join(output_dir, 'estadisticas_descriptivas.csv')
        stats.to_csv(stats_path, header=["Valor"])
        feedback.pushInfo(f"Estadísticas calculadas y guardadas en: {stats_path}")
        
        # Gráfico de distribución
        dist_path = os.path.join(output_dir, 'distribucion_histograma.png')
        plt.figure(figsize=(10, 6))
        sns.histplot(df['Z'], kde=True, bins=15, color="skyblue")
        plt.title(f"Distribución del campo {field_name}")
        plt.xlabel(field_name)
        plt.ylabel("Frecuencia")
        plt.grid(True, alpha=0.3)
        plt.savefig(dist_path, dpi=150, bbox_inches='tight')
        plt.close()
        
        # 2. Nube de semivarianza entre pares
        feedback.pushInfo("Calculando nube de semivarianza entre pares...")
        pares = []
        for (i1, p1), (i2, p2) in combinations(df.iterrows(), 2):
            if feedback.isCanceled():
                return {}
                
            dist = np.sqrt((p2['X'] - p1['X'])**2 + (p2['Y'] - p1['Y'])**2)
            gamma = 0.5 * (p2['Z'] - p1['Z'])**2
            pares.append({
                "Distancia": dist,
                "Semivarianza": gamma
            })
            
        df_pares = pd.DataFrame(pares)
        
        # Filtrar distancias (hasta 1/3 de la diagonal para mejor visualización, o simplemente mostrar todo)
        # Nube de puntos scatter
        nube_path = os.path.join(output_dir, 'nube_semivarianza.png')
        plt.figure(figsize=(10, 6))
        plt.scatter(df_pares['Distancia'], df_pares['Semivarianza'], alpha=0.4, color="purple", s=15)
        plt.title("Nube de Semivarianza (Pares de Puntos)")
        plt.xlabel("Distancia (Lag)")
        plt.ylabel("Semivarianza")
        plt.grid(True, alpha=0.3)
        plt.savefig(nube_path, dpi=150, bbox_inches='tight')
        plt.close()

        # Generar Reporte HTML
        html_path = os.path.join(output_dir, 'reporte_analisis.html')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(f'''
            <html>
            <head>
                <title>Análisis Exploratorio Kriging</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 40px; color: #333; }}
                    h1, h2 {{ color: #2c3e50; }}
                    .container {{ max-width: 900px; margin: auto; }}
                    table {{ border-collapse: collapse; width: 50%; margin-bottom: 20px; }}
                    th, td {{ padding: 10px; border: 1px solid #ddd; text-align: left; }}
                    th {{ background-color: #f4f4f4; }}
                    .img-container {{ text-align: center; margin: 20px 0; }}
                    img {{ max-width: 100%; border: 1px solid #ccc; padding: 5px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>Análisis Exploratorio de Datos (Previo a Kriging)</h1>
                    <p><strong>Campo Analizado:</strong> {field_name}</p>
                    <p><strong>Número de Puntos:</strong> {n}</p>
                    
                    <h2>1. Estadística Descriptiva</h2>
                    {stats.to_frame(name="Valor").to_html(classes="table")}
                    
                    <div class="img-container">
                        <h3>Distribución de Valores (Histograma)</h3>
                        <img src="distribucion_histograma.png" alt="Histograma">
                        <p><em>Evalúa si los datos tienen una distribución normal. Kriging asume normalidad para mejores resultados.</em></p>
                    </div>
                    
                    <h2>2. Estructura Espacial</h2>
                    <div class="img-container">
                        <h3>Nube de Semivarianza de Pares</h3>
                        <img src="nube_semivarianza.png" alt="Nube Semivarianza">
                        <p><em>La nube muestra la disimilitud entre cada par de puntos en función de su distancia. Esta es la base para construir el semivariograma empírico.</em></p>
                    </div>
                </div>
            </body>
            </html>
            ''')
            
        feedback.pushInfo("Análisis completado exitosamente.")
        return {'OUTPUT_DIR': output_dir}
