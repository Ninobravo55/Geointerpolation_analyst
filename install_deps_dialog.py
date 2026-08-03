import sys
import os
import tempfile
from qgis.PyQt.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QLabel
from qgis.PyQt.QtCore import QProcess

def qprocess_merged_channels():
    # PyQt5 and PyQt6 compatibility
    try:
        from qgis.PyQt.QtCore import QProcess
        return QProcess.MergedChannels
    except AttributeError:
        from qgis.PyQt.QtCore import QProcess
        return QProcess.ProcessChannelMode.MergedChannels

class InstallDepsDialog(QDialog):
    def __init__(self, missing_deps, parent=None, installed_deps=None):
        super().__init__(parent)
        self.missing_deps = missing_deps
        self.installed_deps = installed_deps or []
        self.setWindowTitle("Instalando Dependencias de GeoInterpolation Analyst")
        self.resize(650, 450)
        self.layout = QVBoxLayout(self)

        info_text = ""
        if self.installed_deps:
            info_text += "<span style='color:#2E8B57;'>✅ Ya instalados: <b>" + ", ".join(self.installed_deps) + "</b></span><br>"
        info_text += (
            f"⬇️ Instalando paquetes faltantes: <b>{', '.join(missing_deps)}</b><br>"
            "Por favor espera, no cierres esta ventana. El proceso puede tomar unos minutos dependiendo de la conexión a internet."
        )
        self.info_label = QLabel(info_text)
        self.info_label.setWordWrap(True)
        self.layout.addWidget(self.info_label)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setStyleSheet(
            "background-color: #1e1e1e; color: #00FF00; font-family: 'Consolas', 'Courier New', monospace; font-size: 12px; padding: 5px;")
        self.layout.addWidget(self.text_edit)

        self.close_btn = QPushButton("Cerrar (Instalación en progreso...)")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)
        self.layout.addWidget(self.close_btn)

        self.process = QProcess(self)
        self.process.setProcessChannelMode(qprocess_merged_channels())
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.finished.connect(self.process_finished)

        self.start_installation()

    def start_installation(self):
        deps = ' '.join(self.missing_deps)
        osgeo4w_root = os.environ.get('OSGEO4W_ROOT')

        break_pkg = " --break-system-packages" if sys.version_info >= (3, 11) else ""

        try:
            from qgis.core import QgsApplication
            target_dir = os.path.join(QgsApplication.qgisSettingsDirPath(), "python")
        except Exception:
            target_dir = ""

        target_arg = f'--target "{target_dir}"' if target_dir else '--user'

        self.text_edit.append("Iniciando instalación de dependencias...\n")

        if os.name == 'nt' and osgeo4w_root and os.path.exists(os.path.join(osgeo4w_root, 'OSGeo4W.bat')):
            bat_path = os.path.join(osgeo4w_root, 'OSGeo4W.bat')
            script_content = f"""@echo off
echo ========================================================
echo Instalando dependencias de GeoInterpolation Analyst...
echo ========================================================
call "{bat_path}" python -m pip install {deps} {target_arg} --disable-pip-version-check{break_pkg}
echo.
echo ========================================================
echo Ejecucion finalizada.
echo ========================================================
"""
            self.temp_bat = os.path.join(tempfile.gettempdir(), "install_geointerpolation_deps.bat")
            with open(self.temp_bat, "w") as f:
                f.write(script_content)

            self.text_edit.append(f"$ cmd.exe /c {self.temp_bat}\n")
            self.process.start("cmd.exe", ["/c", self.temp_bat])
        else:
            python_exe = os.path.join(sys.exec_prefix, 'bin', 'python3') if os.name != 'nt' else os.path.join(sys.exec_prefix, 'python.exe')
            cmd_args = ["-m", "pip", "install", *self.missing_deps]
            if target_dir:
                cmd_args.extend(["--target", target_dir])
            else:
                cmd_args.append("--user")
            cmd_args.append("--disable-pip-version-check")
            if sys.version_info >= (3, 11):
                cmd_args.append("--break-system-packages")

            cmd_str = f"{python_exe} {' '.join(cmd_args)}"
            self.text_edit.append(f"$ {cmd_str}\n")
            self.process.start(python_exe, cmd_args)

    def handle_stdout(self):
        data = self.process.readAllStandardOutput()
        stdout = bytes(data).decode("utf8", errors="replace")
        self.text_edit.insertPlainText(stdout)
        scrollbar = self.text_edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def process_finished(self, exitCode, exitStatus):
        self.close_btn.setText("Cerrar")
        self.close_btn.setEnabled(True)
        if exitCode == 0:
            self.info_label.setText("<b>¡Instalación completada con éxito!</b> Por favor, <b>REINICIA QGIS</b> para aplicar los cambios.")
            self.info_label.setStyleSheet("color: #2E8B57; font-size: 13px;")
            self.text_edit.append("\n>>> INSTALACIÓN EXITOSA. Reinicie QGIS.")
        else:
            self.info_label.setText("<b>La instalación terminó con errores.</b> Revisa la consola para más detalles.")
            self.info_label.setStyleSheet("color: #D32F2F; font-size: 13px;")
            self.text_edit.append("\n>>> ERROR EN LA INSTALACIÓN.")

        try:
            if hasattr(self, 'temp_bat') and os.path.exists(self.temp_bat):
                os.remove(self.temp_bat)
        except BaseException:
            pass
