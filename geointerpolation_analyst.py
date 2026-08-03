# -*- coding: utf-8 -*-
from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QFileDialog, QMessageBox, QMenu

import os.path

# Initialize Qt resources from file resources.py
# from .resources import *
from .geointerpolation_analyst_dialog import GeoInterpolationAnalystDialog
from qgis.core import QgsApplication
from .provider import GeoInterpolationProvider


class GeoInterpolationAnalyst:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = 'GeoInterpolation Analyst'
        
        self.first_start = None
        self.dlg = None
        self.engine = None
        self.provider = None
        self.main_menu = None

    def initProcessing(self):
        """Init Processing provider for QGIS >= 3.8."""
        self.provider = GeoInterpolationProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        """Create the menu entries inside the QGIS GUI."""
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        self.icon = QIcon(icon_path)
        
        # 1. Menú principal del plugin en Complementos / Plugins
        self.main_menu = QMenu(self.menu, self.iface.mainWindow())
        self.main_menu.setIcon(self.icon)
        self.iface.pluginMenu().addMenu(self.main_menu)

        # 2. Submenú "Análisis de datos"
        self.menu_datos = self.main_menu.addMenu(self.icon, 'Análisis de datos')

        self.action_estadistico = QAction(self.icon, 'Análisis Estadístico', self.iface.mainWindow())
        self.action_estadistico.triggered.connect(self.run)
        self.menu_datos.addAction(self.action_estadistico)
        self.actions.append(self.action_estadistico)
            
        self.action_voronoi = QAction(self.icon, 'Mapa de Voronoi', self.iface.mainWindow())
        self.action_voronoi.triggered.connect(self.run_voronoi)
        self.menu_datos.addAction(self.action_voronoi)
        self.actions.append(self.action_voronoi)

        # 3. Submenú "Interpolación"
        self.menu_interp = self.main_menu.addMenu(self.icon, 'Interpolación')
            
        self.action_idw = QAction(self.icon, 'Interpolación IDW con LOOCV', self.iface.mainWindow())
        self.action_idw.triggered.connect(self.run_idw_loocv)
        self.menu_interp.addAction(self.action_idw)
        self.actions.append(self.action_idw)
        
        self.action_rbf = QAction(self.icon, 'Interpolación Base Radial con LOOCV', self.iface.mainWindow())
        self.action_rbf.triggered.connect(self.run_rbf_loocv)
        self.menu_interp.addAction(self.action_rbf)
        self.actions.append(self.action_rbf)
        
        self.menu_interp.addSeparator()
        
        self.action_kriging_data = QAction(self.icon, '1. Análisis Exploratorio Kriging', self.iface.mainWindow())
        self.action_kriging_data.triggered.connect(self.run_kriging_data)
        self.menu_interp.addAction(self.action_kriging_data)
        self.actions.append(self.action_kriging_data)
        
        self.action_kriging_variogram = QAction(self.icon, '2. Análisis de Variograma', self.iface.mainWindow())
        self.action_kriging_variogram.triggered.connect(self.run_kriging_variogram)
        self.menu_interp.addAction(self.action_kriging_variogram)
        self.actions.append(self.action_kriging_variogram)
        
        self.action_kriging = QAction(self.icon, '3. Interpolación Kriging Ordinario', self.iface.mainWindow())
        self.action_kriging.triggered.connect(self.run_kriging)
        self.menu_interp.addAction(self.action_kriging)
        self.actions.append(self.action_kriging)
            
        # 4. Separador y acción Instalar Dependencias
        self.main_menu.addSeparator()
        self.action_install_deps = QAction(self.icon, 'Instalar Dependencias', self.iface.mainWindow())
        self.action_install_deps.triggered.connect(self.install_deps)
        self.main_menu.addAction(self.action_install_deps)
        self.actions.append(self.action_install_deps)
            
        self.initProcessing()
        self.first_start = True

    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)

        if self.main_menu:
            self.iface.pluginMenu().removeAction(self.main_menu.menuAction())
            self.main_menu.deleteLater()
            self.main_menu = None

    def install_deps(self):
        import importlib
        missing_deps = []
        installed_deps = []
        for pkg in ['seaborn', 'pandas', 'scipy', 'openpyxl', 'pykrige', 'sklearn']:
            try:
                importlib.import_module(pkg)
                installed_deps.append(pkg)
            except ImportError:
                missing_deps.append(pkg)
                
        if not missing_deps:
            QMessageBox.information(self.iface.mainWindow(), "Dependencias", "Todas las dependencias ya están instaladas.")
            return
            
        from .install_deps_dialog import InstallDepsDialog
        dialog = InstallDepsDialog(missing_deps, self.iface.mainWindow(), installed_deps)
        dialog.exec_()

    def run_idw_loocv(self):
        import processing
        processing.execAlgorithmDialog('geointerpolation:idw_loocv')

    def run_rbf_loocv(self):
        import processing
        processing.execAlgorithmDialog('geointerpolation:rbf_loocv')

    def run_kriging_data(self):
        import processing
        processing.execAlgorithmDialog('geointerpolation:kriging_data_analysis')

    def run_kriging_variogram(self):
        import processing
        processing.execAlgorithmDialog('geointerpolation:kriging_variogram')

    def run_kriging(self):
        import processing
        processing.execAlgorithmDialog('geointerpolation:kriging_ordinario')

    def run_voronoi(self):
        import processing
        processing.execAlgorithmDialog('geointerpolation:voronoi')

    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self.dlg, "Seleccionar Archivo de Datos", "", "CSV / Excel (*.csv *.xlsx)"
        )
        if file_path:
            self.dlg.lineEditFile.setText(file_path)
            self.load_variables(file_path)
            
    def select_output_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self.dlg, "Seleccionar Directorio de Salida")
        if dir_path:
            self.dlg.lineEditOutputDir.setText(dir_path)
            
    def load_variables(self, file_path):
        try:
            from .statistics_engine import StatisticsEngine
            self.engine = StatisticsEngine(file_path)
            columns = self.engine.get_numeric_columns()
            
            # Populate coordinate comboboxes
            self.dlg.cbxEste.clear()
            self.dlg.cbxNorte.clear()
            self.dlg.cbxEste.addItem("")
            self.dlg.cbxNorte.addItem("")
            self.dlg.cbxEste.addItems(columns)
            self.dlg.cbxNorte.addItems(columns)
            
            # Auto-select Este / Norte if possible
            este_keywords = ['este', 'x', 'lon', 'longitud']
            norte_keywords = ['norte', 'y', 'lat', 'latitud']
            
            for i, col in enumerate(columns):
                col_lower = col.lower()
                if any(kw == col_lower or kw in col_lower for kw in este_keywords):
                    self.dlg.cbxEste.setCurrentText(col)
                if any(kw == col_lower or kw in col_lower for kw in norte_keywords):
                    self.dlg.cbxNorte.setCurrentText(col)
            
            # Populate list of variables
            self.dlg.listVariables.clear()
            self.dlg.listVariables.addItems(columns)
            
            self.dlg.textEditResults.append("Archivo cargado correctamente. Campos detectados.")
        except ImportError:
            QMessageBox.critical(self.dlg, "Dependencias Faltantes", "Faltan librerías requeridas (ej. seaborn).\nPor favor, vaya al menú 'Complementos > GeoInterpolation Analyst > Instalar Dependencias' y vuelva a intentarlo.")
        except Exception as e:
            QMessageBox.critical(self.dlg, "Error", f"No se pudo cargar el archivo:\n{str(e)}")

    def run_analysis(self):
        if not self.engine:
            QMessageBox.warning(self.dlg, "Advertencia", "Por favor seleccione un archivo primero.")
            return
            
        selected_items = self.dlg.listVariables.selectedItems()
        if not selected_items:
            QMessageBox.warning(self.dlg, "Advertencia", "Por favor seleccione al menos una variable para analizar.")
            return
            
        variables = [item.text() for item in selected_items]
        output_dir = self.dlg.lineEditOutputDir.text()
        
        este_col = self.dlg.cbxEste.currentText()
        norte_col = self.dlg.cbxNorte.currentText()
        
        if not output_dir:
            QMessageBox.warning(self.dlg, "Advertencia", "Por favor seleccione un directorio de salida.")
            return
            
        try:
            self.dlg.textEditResults.append(f"\n--- Iniciando Análisis ---")
            if este_col and norte_col:
                self.dlg.textEditResults.append(f"Coordenadas X: {este_col} | Y: {norte_col}")
                
            apply_boxcox = self.dlg.chkBoxCox.isChecked()
            stats_dict = {}
            lambda_results = {}
            
            for variable in variables:
                if variable in [este_col, norte_col]:
                    continue # Skip stats for coordinate columns if they were accidentally selected
                    
                stats = self.engine.calculate_statistics(variable)
                stats_dict[variable] = stats

                
                result_text = f"\n=== Resultados para {variable} ===\n"
                result_text += f"N (Conteo): {stats['count']}\n"
                
                result_text += f"[Tendencia Central] Media: {stats['mean']:.4f} | Mediana: {stats['median']:.4f} | Moda: {stats['mode']}\n"
                result_text += f"[Dispersión] Varianza: {stats['variance']:.4f} | Desv. Estándar: {stats['std_dev']:.4f} | Rango: {stats['range']:.4f}\n"
                result_text += f"[Posición Relativa] Q1: {stats['q1']:.4f} | Q2: {stats['q2']:.4f} | Q3: {stats['q3']:.4f} | P90: {stats['p90']:.4f}\n"
                result_text += f"[Forma] Asimetría: {stats['skewness']:.4f} | Curtosis: {stats['kurtosis']:.4f}\n"
                result_text += f"[Normalidad] p-value Shapiro: {stats['pvalue_shapiro']:.4f} -> {stats['distribucion']}\n"
                
                self.dlg.textEditResults.append(result_text)
                
                if apply_boxcox:
                    # Apply ONLY if the distribution is not normal (p-value <= 0.05)
                    if stats.get('pvalue_shapiro', 1) <= 0.05:
                        best_lambda, boxcox_p_value = self.engine.apply_best_boxcox(variable)
                        if best_lambda is not None:
                            lambda_results[variable] = {'lambda': best_lambda, 'p_value': boxcox_p_value}
                            self.dlg.textEditResults.append(f"[Box-Cox] Aplicado por no ser normal. Mejor lambda: {best_lambda} con p-valor de {boxcox_p_value:.4f}")
                        else:
                            self.dlg.textEditResults.append(f"[Box-Cox] Advertencia: {boxcox_p_value}")
                    else:
                        self.dlg.textEditResults.append(f"[Box-Cox] Ignorado: La variable ya tiene distribución normal.")
                
                # Graficos
                hist_path, box_path = self.engine.generate_graphs(variable, output_dir)
                self.dlg.textEditResults.append(f"Gráficos guardados: {variable}_histogram.png, {variable}_boxplot.png")
            
            self.dlg.textEditResults.append("=========================\n")
            
            if self.dlg.chkStatsTable.isChecked():
                out_table = self.engine.export_statistics_table(stats_dict, output_dir)
                if out_table:
                    self.dlg.textEditResults.append(f"Tabla de resumen estadístico guardada en: {out_table}")
                    
            if apply_boxcox and lambda_results:
                out_lambda = self.engine.export_lambda_summary(lambda_results, output_dir)
                out_dataset = self.engine.export_transformed_dataset(output_dir)
                self.dlg.textEditResults.append(f"Resumen de lambdas guardado en: {out_lambda}")
                self.dlg.textEditResults.append(f"Dataset transformado guardado en: {out_dataset}")
                    
            if self.dlg.chkLayer.isChecked() and este_col and norte_col:
                self.create_spatial_layer(este_col, norte_col, output_dir, self.crs_selector.crs())
                
            QMessageBox.information(self.dlg, "Éxito", "Análisis completado exitosamente.")
            
        except Exception as e:
            QMessageBox.critical(self.dlg, "Error", f"Ocurrió un error en el análisis:\n{str(e)}")

    def create_spatial_layer(self, x_col, y_col, output_dir, crs):
        import os
        import pandas as pd
        from qgis.core import QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY, QgsVectorFileWriter, QgsProject, QgsField
        from qgis.PyQt.QtCore import QVariant
        
        try:
            df = self.engine.df
            
            # Crear capa de memoria
            layer = QgsVectorLayer(f"Point?crs={crs.authid()}", "Analisis_Suelos", "memory")
            provider = layer.dataProvider()
            
            # Crear campos basados en el dataframe
            fields = []
            for col in df.columns:
                dtype = df[col].dtype
                if 'float' in str(dtype):
                    fields.append(QgsField(str(col), QVariant.Double))
                elif 'int' in str(dtype):
                    fields.append(QgsField(str(col), QVariant.Int))
                else:
                    fields.append(QgsField(str(col), QVariant.String))
            provider.addAttributes(fields)
            layer.updateFields()
            
            # Anadir features
            features = []
            for index, row in df.iterrows():
                try:
                    x = float(row[x_col])
                    y = float(row[y_col])
                    
                    feat = QgsFeature(layer.fields())
                    feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
                    
                    # Set attributes
                    for i, col in enumerate(df.columns):
                        val = row[col]
                        if not pd.isna(val):
                            feat.setAttribute(i, str(val) if 'object' in str(df[col].dtype) else val)
                    features.append(feat)
                except Exception:
                    continue
                    
            provider.addFeatures(features)
            layer.updateExtents()
            
            # Guardar a GeoPackage
            output_path = os.path.join(output_dir, "Capa_Suelos.gpkg")
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            
            error = QgsVectorFileWriter.writeAsVectorFormatV3(layer, output_path, layer.transformContext(), options)
            if error[0] == QgsVectorFileWriter.NoError:
                self.dlg.textEditResults.append(f"Capa espacial generada: {output_path}")
                
                # Cargar en QGIS
                vlayer = QgsVectorLayer(output_path, "Resultados Analisis Espacial", "ogr")
                if vlayer.isValid():
                    QgsProject.instance().addMapLayer(vlayer)
            else:
                self.dlg.textEditResults.append(f"Error al guardar la capa espacial: {error[1]}")
                
        except Exception as e:
            self.dlg.textEditResults.append(f"Error generando capa espacial: {str(e)}")

    def run(self):
        """Run method that performs all the real work"""
        if self.first_start:
            self.first_start = False
            self.dlg = GeoInterpolationAnalystDialog()
            
            # Initialize CRS selector
            from qgis.gui import QgsProjectionSelectionWidget
            from qgis.core import QgsProject
            self.crs_selector = QgsProjectionSelectionWidget()
            self.crs_selector.setCrs(QgsProject.instance().crs())
            self.dlg.crsLayout.addWidget(self.crs_selector)
            
            # Connect signals
            self.dlg.btnBrowseFile.clicked.connect(self.select_file)
            self.dlg.btnBrowseOutput.clicked.connect(self.select_output_dir)
            self.dlg.btnAnalyze.clicked.connect(self.run_analysis)

        # show the dialog
        self.dlg.show()
        result = self.dlg.exec_()
        if result:
            pass
