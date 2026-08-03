# -*- coding: utf-8 -*-
import pandas as pd
import numpy as np
from scipy.stats import skew, kurtosis, shapiro
import matplotlib.pyplot as plt
import seaborn as sns
import os

class StatisticsEngine:
    """
    Engine to process tabular data and calculate statistical measures.
    Calculates Central Tendency, Dispersion, Relative Position, and Shape.
    """
    def __init__(self, filepath):
        self.filepath = filepath
        self.df = self._load_data()
        
    def _load_data(self):
        if self.filepath.endswith('.csv'):
            return pd.read_csv(self.filepath)
        elif self.filepath.endswith('.xlsx'):
            return pd.read_excel(self.filepath)
        else:
            raise ValueError("Unsupported file format. Please provide .csv or .xlsx")
            
    def get_numeric_columns(self):
        return self.df.select_dtypes(include=[np.number]).columns.tolist()
        
    def calculate_statistics(self, column_name):
        if column_name not in self.df.columns:
            raise ValueError(f"Column {column_name} not found in the dataset.")
            
        data = self.df[column_name].dropna()
        
        if data.empty:
            raise ValueError(f"Column {column_name} is empty or all NaN.")
            
        # Tendencia Central
        mean = data.mean()
        median = data.median()
        mode = data.mode().iloc[0] if not data.mode().empty else np.nan
        
        # Dispersión
        variance = data.var()
        std_dev = data.std()
        data_range = data.max() - data.min()
        
        # Posición Relativa
        q1 = data.quantile(0.25)
        q2 = data.quantile(0.50) # Same as median
        q3 = data.quantile(0.75)
        p90 = data.quantile(0.90)
        
        # Identificar Valores atípicos (Outliers) en self.df
        iqr = q3 - q1
        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr
        
        outlier_col = f"{column_name}_outlier"
        cond_outlier = (self.df[column_name] < lower_bound) | (self.df[column_name] > upper_bound)
        cond_notnull = self.df[column_name].notna()
        
        # Asignar valores usando pandas de forma segura para evitar problemas de dtype
        self.df[outlier_col] = 'No'
        self.df.loc[cond_outlier, outlier_col] = 'Sí'
        self.df.loc[~cond_notnull, outlier_col] = np.nan

        # Forma
        skewness = skew(data)
        kurt = kurtosis(data)
        
        # Prueba de normalidad de Shapiro-Wilk
        if len(data) >= 3:
            stat_shapiro, pvalue_shapiro = shapiro(data)
            distribucion = "Distribución normal" if pvalue_shapiro > 0.05 else "No distribución normal"
        else:
            pvalue_shapiro = np.nan
            distribucion = "Insuficientes datos"
        
        return {
            'mean': mean,
            'median': median,
            'mode': mode,
            'variance': variance,
            'std_dev': std_dev,
            'range': data_range,
            'q1': q1,
            'q2': q2,
            'q3': q3,
            'p90': p90,
            'skewness': skewness,
            'kurtosis': kurt,
            'pvalue_shapiro': pvalue_shapiro,
            'distribucion': distribucion,
            'count': len(data)
        }
        
    def generate_graphs(self, column_name, output_dir):
        """
        Generates Histogram and Boxplot for the given column and saves them in output_dir.
        """
        data = self.df[column_name].dropna()
        
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        # Set Seaborn style
        sns.set(style="whitegrid")
        
        # 1. Histogram (Tendencia Central y Forma)
        plt.figure(figsize=(8, 6))
        sns.histplot(data, kde=True, color="blue", bins=15)
        plt.title(f'Histograma y Curva de Densidad - {column_name}')
        plt.xlabel(column_name)
        plt.ylabel('Frecuencia')
        hist_path = os.path.join(output_dir, f"{column_name}_histogram.png")
        plt.savefig(hist_path, bbox_inches='tight')
        plt.close()
        
        # 2. Boxplot (Dispersión y Posición Relativa)
        plt.figure(figsize=(8, 6))
        sns.boxplot(y=data, color="cyan")
        plt.title(f'Boxplot (Diagrama de Caja) - {column_name}')
        plt.ylabel(column_name)
        box_path = os.path.join(output_dir, f"{column_name}_boxplot.png")
        plt.savefig(box_path, bbox_inches='tight')
        return hist_path, box_path
        
    def export_statistics_table(self, stats_dict, output_dir):
        """
        Exports a summary of statistics to an Excel file.
        stats_dict: { 'variable_name': { 'mean': ..., 'median': ... } }
        """
        if not stats_dict:
            return None
            
        df_stats = pd.DataFrame.from_dict(stats_dict, orient='index')
        
        # Reordenar columnas y renombrar para presentacion
        cols_order = ['count', 'mean', 'median', 'mode', 'variance', 'std_dev', 'range', 'q1', 'q2', 'q3', 'p90', 'skewness', 'kurtosis', 'pvalue_shapiro', 'distribucion']
        df_stats = df_stats[cols_order]
        
        df_stats.columns = ['N', 'Media', 'Mediana', 'Moda', 'Varianza', 'Desv. Estandar', 'Rango', 'Q1', 'Q2', 'Q3', 'P90', 'Asimetria', 'Curtosis', 'p-value (Shapiro)', 'Distribucion']
        
        out_path = os.path.join(output_dir, "Resumen_Estadistico.xlsx")
        df_stats.to_excel(out_path, index_label="Variable")
        
        return out_path

    def _box_cox_manual(self, data, lambda_val):
        data = data.astype(float)
        if (data <= 0).any():
            raise ValueError("Todos los valores deben ser positivos para aplicar Box-Cox")
        if lambda_val == 0:
            return np.log(data)
        else:
            return (data ** lambda_val - 1) / lambda_val
            
    def apply_best_boxcox(self, column_name):
        data = self.df[column_name].dropna()
        if (data <= 0).any():
            return None, "Valores no positivos encontrados. Box-Cox ignorado."
            
        lambda_values = [-2, -1, -0.5, 0, 0.5, 2]
        results_K = {}
        
        for lambda_val in lambda_values:
            try:
                transformed_data = self._box_cox_manual(data, lambda_val)
                stat, p_value = shapiro(transformed_data)
                results_K[lambda_val] = p_value
            except Exception:
                continue
                
        if not results_K:
            return None, "Error aplicando Box-Cox."
            
        best_lambda = max(results_K, key=results_K.get)
        best_p_value = results_K[best_lambda]
        
        # Apply transformation with best lambda and save to dataframe
        new_col_name = f"{column_name}_boxcox"
        self.df[new_col_name] = self._box_cox_manual(self.df[column_name], best_lambda)
        
        return best_lambda, best_p_value
        
    def export_lambda_summary(self, lambda_results, output_dir):
        """
        Exports a summary of the best lambdas chosen for each variable.
        lambda_results: { 'variable_name': {'lambda': ..., 'p_value': ...} }
        """
        if not lambda_results:
            return None
            
        df_lambda = pd.DataFrame.from_dict(lambda_results, orient='index')
        df_lambda.columns = ['Mejor Lambda', 'p-value (Shapiro)']
        
        out_path = os.path.join(output_dir, "Resumen_Lambdas_BoxCox.xlsx")
        df_lambda.to_excel(out_path, index_label="Variable")
        
        return out_path
        
    def export_transformed_dataset(self, output_dir):
        out_path = os.path.join(output_dir, "Dataset_Transformado.xlsx")
        self.df.to_excel(out_path, index=False)
        return out_path
