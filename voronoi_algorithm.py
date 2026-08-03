import os
from qgis.PyQt.QtCore import QCoreApplication
import processing
from qgis.core import (
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterExtent,
)

class VoronoiAlgorithm(QgsProcessingAlgorithm):
    INPUT = 'INPUT'
    EXTENT = 'EXTENT'
    OUTPUT = 'OUTPUT'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return VoronoiAlgorithm()

    def name(self):
        return 'voronoi'

    def displayName(self):
        return self.tr('Mapa de Voronoi con Extensión de Estudio')

    def group(self):
        return self.tr('Análisis de datos')

    def groupId(self):
        return 'analisis_datos'

    def shortHelpString(self):
        return self.tr(
            "Esta herramienta genera polígonos de Voronoi a partir de una capa de puntos "
            "y recorta el resultado usando una capa de polígonos que define la extensión del estudio. "
            "El resultado conserva todos los campos de la capa de puntos de entrada."
        )

    def initAlgorithm(self, config=None):
        # 1. Capa de puntos de entrada
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT, 
                self.tr('Capa de puntos de entrada'), 
                [QgsProcessing.TypeVectorPoint]
            )
        )
        # 2. Extensión del estudio (Extent)
        self.addParameter(
            QgsProcessingParameterExtent(
                self.EXTENT, 
                self.tr('Extensión del estudio (dibujar en el lienzo)')
            )
        )
        # 3. Capa de salida
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT, 
                self.tr('Polígonos de Voronoi')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        input_points = self.parameterAsSource(parameters, self.INPUT, context)
        
        if input_points is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))
        if self.parameterAsString(parameters, self.EXTENT, context) == '':
            raise QgsProcessingException("Debe definir la extensión del estudio.")

        feedback.pushInfo(self.tr("Generando polígonos de Voronoi..."))

        # Paso 1: Generar Voronoi con un buffer grande (ej. 100%) para cubrir el área de estudio
        voronoi_result = processing.run(
            'qgis:voronoipolygons',
            {
                'INPUT': parameters[self.INPUT],
                'BUFFER': 100,
                'OUTPUT': 'memory:voronoi_temp'
            },
            context=context,
            feedback=feedback,
            is_child_algorithm=True
        )

        if feedback.isCanceled():
            return {}

        feedback.pushInfo(self.tr("Convirtiendo extensión a polígono..."))
        extent_polygon = processing.run(
            'native:extenttolayer',
            {
                'INPUT': parameters[self.EXTENT],
                'OUTPUT': 'memory:extent_poly'
            },
            context=context,
            feedback=feedback,
            is_child_algorithm=True
        )

        if feedback.isCanceled():
            return {}

        feedback.pushInfo(self.tr("Recortando polígonos de Voronoi con la extensión..."))

        # Paso 2: Recortar los polígonos de Voronoi con el polígono de extensión
        clip_result = processing.run(
            'native:clip',
            {
                'INPUT': voronoi_result['OUTPUT'],
                'OVERLAY': extent_polygon['OUTPUT'],
                'OUTPUT': parameters[self.OUTPUT]
            },
            context=context,
            feedback=feedback,
            is_child_algorithm=True
        )
        
        if feedback.isCanceled():
            return {}

        return {self.OUTPUT: clip_result['OUTPUT']}
