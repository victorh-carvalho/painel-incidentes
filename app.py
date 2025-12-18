import streamlit as st
import pandas as pd
import re
import io
from datetime import timedelta

# --- 1. Configurações e Funções Auxiliares ---
st.set_page_config(page_title="Central de Incidentes Unificada", layout="wide", page_icon="🧩")

MESES_PT = {
    'jan': '01', 'fev': '02', 'mar': '03', 'abr': '04', 'mai': '05', 'jun': '06',
    'jul': '07', 'ago': '08', 'set': '09', 'out': '10', 'nov': '11', 'dez': '12'
}

def carregar_csv_seguro(arquivo):
    """Tenta ler o CSV com diferentes encodings e separadores"""
    encodings = ['utf-8', 'latin-1', 'cp1252']
    separadores = [',', ';']
    
    arquivo.seek(0)
    for enc in encodings:
        for sep in separadores:
            try:
                arquivo.seek(0)
                df = pd.read_csv(arquivo, sep=sep, encoding=enc)
                if df.shape[1] > 1:
                    return df
            except:
                continue
    return None

def limpar_data_pt(data_str):
    """Converte datas como '17 de dez. de 2025' para datetime"""
    if not isinstance(data_str, str): return pd.NaT
    try:
        clean = data_str.replace('de ', '').replace('.', '').lower()
        parts = clean.split()
        if len(parts) >= 3:
            day, month_txt, year = parts[0], parts[1], parts[2]
            # Tenta pegar hora se existir
            time = parts[3] if len(parts) > 3 else "00:00:00"
            month_num = MESES_PT.get(month_txt[:3], '01')
            return pd.to_datetime(f"{year}-{month_num}-{day} {time}")
    except:
        return pd.NaT
    return pd.NaT

def extrair_falha_regex(texto):
    if not isinstance(texto, str): return "Não Identificado"
    # Se for texto curto (Resumo), retorna ele mesmo
    if len(texto) < 50 and "Tipo da falha" not in texto:
        return texto.strip()
    
    padrao = r"(?:Tipo d?e? falha|Tp\.? falha|Falha):\s*(.*?)(?:\n|$)"
    match = re.search(padrao, texto, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return "Não Identificado"

def processar_sla(df, col_data, col_prazo_existente=None):
    # Tenta achar a coluna de data disponível
    if col_data not in df.columns:
        # Tenta fallback para outras colunas de data comuns
        cols_alternativas = ['Data da última modificação', 'Data de criação', 'Data Hora de Abertura']
        for c in cols_alternativas:
            if c in df.columns:
                col_data = c
                break
    
    # Se ainda não achou, cria coluna vazia
    if col_data not in df.columns:
        df['Data_Abertura_Formatada'] = pd.NaT
    else:
        # Converte coluna de data
        df['Data_Abertura_Formatada'] = pd.to_datetime(df[col_data], dayfirst=True, errors='coerce')
        # Fallback para formato texto PT-BR se a conversão direta falhar
        mask_nat = df['Data_Abertura_Formatada'].isna()
        if mask_nat.any():
            df.loc[mask_nat, 'Data_Abertura_Formatada'] = df.loc[mask_nat, col_data].apply(limpar_data_pt)

    # Define o Prazo SLA
    if col_prazo_existente and col_prazo_existente in df.columns:
        df['Prazo_SLA'] = pd.to_datetime(df[col_prazo_existente], dayfirst=True, errors='coerce')
        # Preenche vazios com regra de 24h
        idx_na = df['Prazo_SLA'].isna()
        df.loc[idx_na, 'Prazo_SLA'] = df.loc[idx_na, 'Data_Abertura_Formatada'] + timedelta(hours=24)
    else:
        # Regra de +24h se não tiver data de prazo
        df['Prazo_SLA'] = df['Data_Abertura_Formatada'] + timedelta(hours=24)
        
    return df

def converter_df_para_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Unificado')
    return output.getvalue()

# --- 2. Interface Principal ---
st.title("🧩 Unificador de Incidentes e SLA")
st.markdown("Faça o upload dos dois arquivos abaixo.")

col_up1, col_up2 = st.columns(2)

with col_up1:
    st.info("Arquivo do **Turing/Helix** (Grid)")
    file_grid = st.file_uploader("Upload CSV Grid", type=['csv'], key="f1")

with col_up2:
    st.info("Arquivo do **Cherwell** (Export)")
    file_export = st.file_uploader("Upload CSV Export", type=['csv'], key="f2")

if file_grid and file_export:
    st.divider()
    if st.button("Processar e Unificar Arquivos 🚀"):
        try:
            # --- PROCESSAMENTO ARQUIVO GRID (TCloud) ---
            df_grid = carregar_csv_seguro(file_grid)
            
            if df_grid is None:
                st.error("Erro ao ler o arquivo Grid. Verifique se é um CSV válido.")
                st.stop()

            # Lógica inteligente para achar a coluna de Falha/Descrição
            col_falha_grid = 'Descrição'
            if 'Descrição' not in df_grid.columns:
                if 'Resumo' in df_grid.columns:
                    col_falha_grid = 'Resumo'
                else:
                    st.error("Não encontrei coluna de 'Descrição' nem 'Resumo' no arquivo Grid.")
                    st.stop()
            
            # Normalização Grid
            df_grid['Tipo_Falha_Unificado'] = df_grid[col_falha_grid].apply(extrair_falha_regex)
            
            # Data: Tenta 'Data de criação', se não tiver vai de 'Data da última modificação'
            col_data_grid = 'Data de criação'
            if col_data_grid not in df_grid.columns:
                col_data_grid = 'Data da última modificação'

            df_grid = processar_sla(df_grid, col_data_grid)
            
            # Renomeia colunas
            # Garante colunas de saida
            if 'Exibir ID' not in df_grid.columns:
                 # Tenta achar ID se tiver nome diferente
                 df_grid['Exibir ID'] = df_grid.index 
            
            df_grid_final = df_grid[['Exibir ID', 'Tipo_Falha_Unificado', 'Data_Abertura_Formatada', 'Prazo_SLA']].copy()
            df_grid_final.columns = ['ID', 'Tipo_Falha', 'Data_Abertura', 'Prazo_SLA']
            df_grid_final['Origem'] = 'Grid (TCloud)'

            # --- PROCESSAMENTO ARQUIVO EXPORT (Cherwell) ---
            df_export = carregar_csv_seguro(file_export)
            
            if df_export is None:
                st.error("Erro ao ler o arquivo Export. Verifique se é um CSV válido.")
                st.stop()

            # >>> FILTRO DE TIME RESPONSÁVEL <<<
            if 'Equipe Responsável' in df_export.columns:
                filtro_time = 'TCLOUD-DEVOPS-PROTHEUS'
                df_export['Equipe Responsável'] = df_export['Equipe Responsável'].astype(str).str.strip()
                df_export = df_export[df_export['Equipe Responsável'] == filtro_time].copy()
            else:
                st.warning("Coluna 'Equipe Responsável' não encontrada no arquivo Export. Verifique se carregou o arquivo certo.")

            # Identifica colunas
            col_tipo_export = 'Assunto' if 'Assunto' in df_export.columns else df_export.columns[0]
            col_id_export = 'Número' if 'Número' in df_export.columns else 'ID'
            
            # Normalização Export
            if col_tipo_export in df_export.columns:
                # Pega texto antes do hífen
                df_export['Tipo_Falha_Unificado'] = df_export[col_tipo_export].astype(str).str.split('-').str[0].str.strip()
            else:
                df_export['Tipo_Falha_Unificado'] = 'N/A'
            
            df_export = processar_sla(df_export, 'Data Hora de Abertura', 'Resolver até')

            # Renomeia
            cols_export = [col_id_export, 'Tipo_Falha_Unificado', 'Data_Abertura_Formatada', 'Prazo_SLA']
            
            # Verifica se colunas existem antes de selecionar
            cols_ok = [c for c in cols_export if c in df_export.columns]
            df_export_final = df_export[cols_ok].copy()
            
            # Renomeia na força bruta se a ordem estiver certa (garantindo estrutura)
            if len(df_export_final.columns) == 4:
                df_export_final.columns = ['ID', 'Tipo_Falha', 'Data_Abertura', 'Prazo_SLA']
            
            df_export_final['Origem'] = 'Export System'

            # --- UNIFICAÇÃO ---
            df_unificado = pd.concat([df_grid_final, df_export_final], ignore_index=True)

            # Cálculo de Status SLA
            agora = pd.Timestamp.now()
            df_unificado['Status_SLA'] = df_unificado['Prazo_SLA'].apply(
                lambda x: '🚨 Vencido' if pd.notnull(x) and x < agora else '✅ No Prazo'
            )
            
            # Ordenar por data
            df_unificado = df_unificado.sort_values(by='Data_Abertura', ascending=False)

            # --- EXIBIÇÃO ---
            st.success(f"Sucesso! {len(df_unificado)} incidentes processados.")

            # Métricas
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Geral", len(df_unificado))
            c2.metric("Vencidos", len(df_unificado[df_unificado['Status_SLA'] == '🚨 Vencido']))
            c3.metric("Origem Grid", len(df_grid_final))
            c4.metric("Origem Export", len(df_export_final))

            st.subheader("Tabela Unificada")
            st.dataframe(df_unificado, use_container_width=True)

            # Gráfico
            st.subheader("Top 5 Tipos de Falha")
            if not df_unificado.empty:
                st.bar_chart(df_unificado['Tipo_Falha'].value_counts().head(5))

            # Download
            excel_data = converter_df_para_excel(df_unificado)
            st.download_button(
                label="📥 Baixar Relatório Unificado (.xlsx)",
                data=excel_data,
                file_name="incidentes_unificados.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        except Exception as e:
            st.error(f"Ocorreu um erro técnico: {e}")
            st.write("Detalhe: Verifique se os arquivos não estão vazios ou corrompidos.")