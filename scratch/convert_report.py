import os
import re
import sys
import markdown
from dotenv import load_dotenv

# Carregar variáveis de ambiente do .env
load_dotenv()

# Caminhos dos ficheiros
WORKSPACE_DIR = r"c:\Users\lopes\Music\SASASA\ArteNuvem-main (2) (1)\ArteNuvem-main"
BRAIN_DIR = r"C:\Users\lopes\.gemini\antigravity-ide\brain\8fdb13fd-0e23-4417-920f-2362b6468f98"

FILES_TO_CONVERT = [
    {
        "md": os.path.join(BRAIN_DIR, "relatorio_projeto_artenuvem.md"),
        "pdf": os.path.join(WORKSPACE_DIR, "Relatorio_Tecnico_ArteNuvem.pdf"),
        "temp_html": os.path.join(WORKSPACE_DIR, "temp_relatorio.html"),
        "title": "Relatório Técnico do Projeto",
        "subtitle": "ArteNuvem — Plataforma Digital de Curadoria e Catalogação de Arte",
        "metadata": "Documentação de Base de Dados, APIs Externas, Segurança de Conteúdo e Autenticação"
    },
    {
        "md": os.path.join(BRAIN_DIR, "catalogo_endpoints_artenuvem.md"),
        "pdf": os.path.join(WORKSPACE_DIR, "Catalogo_Endpoints_ArteNuvem.pdf"),
        "temp_html": os.path.join(WORKSPACE_DIR, "temp_endpoints.html"),
        "title": "Catálogo Geral de Endpoints & Guia Postman",
        "subtitle": "ArteNuvem — Especificação de APIs REST v1, Consultas e Rotas Web",
        "metadata": "Guia de Testes para Ambiente Local (Localhost) e Produção (Render)"
    }
]

def convert_file(file_info):
    md_path = file_info["md"]
    pdf_path = file_info["pdf"]
    temp_html_path = file_info["temp_html"]
    
    print(f"\n--- A processar: {file_info['title']} ---")
    if not os.path.exists(md_path):
        print(f"Erro: Ficheiro Markdown não encontrado em {md_path}")
        return False
        
    with open(md_path, "r", encoding="utf-8") as f:
        md_content = f.read()

    print("A converter Markdown para HTML...")
    # Converter para HTML com suporte a tabelas
    html_body = markdown.markdown(md_content, extensions=["tables", "fenced_code"])

    # Substituir os blocos de código mermaid por tags div identificáveis pelo mermaid.js
    html_body = re.sub(
        r'<pre><code class="language-mermaid">([\s\S]*?)</code></pre>',
        r'<div class="mermaid">\1</div>',
        html_body
    )

    # Adicionar estilos premium para impressão do PDF
    premium_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{file_info['title']} - ArteNuvem</title>
    <!-- Fontes do Google -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Outfit:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
    
    <!-- Scripts do Mermaid JS para renderização dos diagramas -->
    <script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
    <script>
        mermaid.initialize({{
            startOnLoad: true,
            theme: 'default',
            securityLevel: 'loose',
            flowchart: {{ useMaxWidth: true, htmlLabels: true }}
        }});
    </script>

    <style>
        @page {{
            size: A4;
            margin: 20mm;
        }}
        body {{
            font-family: 'Inter', sans-serif;
            color: #1e293b;
            line-height: 1.6;
            font-size: 11pt;
            background-color: #ffffff;
            margin: 0;
            padding: 0;
        }}
        h1, h2, h3, h4 {{
            font-family: 'Outfit', sans-serif;
            color: #0f172a;
            font-weight: 700;
            page-break-after: avoid;
        }}
        h1 {{
            font-size: 24pt;
            border-bottom: 2px solid #3b82f6;
            padding-bottom: 8px;
            margin-top: 0;
            margin-bottom: 20px;
        }}
        h2 {{
            font-size: 16pt;
            border-bottom: 1px solid #e2e8f0;
            padding-bottom: 6px;
            margin-top: 30px;
            margin-bottom: 15px;
            page-break-before: auto;
        }}
        h3 {{
            font-size: 12pt;
            margin-top: 20px;
            margin-bottom: 10px;
        }}
        p {{
            margin-top: 0;
            margin-bottom: 15px;
            text-align: justify;
        }}
        /* Tabelas elegantes */
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
            margin-bottom: 20px;
            page-break-inside: avoid;
            font-size: 9.5pt;
        }}
        th, td {{
            border: 1px solid #cbd5e1;
            padding: 8px 10px;
            text-align: left;
        }}
        th {{
            background-color: #f1f5f9;
            color: #0f172a;
            font-weight: 600;
        }}
        tr:nth-child(even) {{
            background-color: #f8fafc;
        }}
        /* Elementos especiais */
        code {{
            font-family: 'Courier New', Courier, monospace;
            background-color: #f1f5f9;
            padding: 2px 4px;
            border-radius: 4px;
            font-size: 9.5pt;
        }}
        .mermaid {{
            display: flex;
            justify-content: center;
            margin: 25px 0;
            page-break-inside: avoid;
            background-color: #fafafa;
            border: 1px solid #f1f5f9;
            border-radius: 8px;
            padding: 15px;
        }}
        ul, ol {{
            margin-top: 0;
            margin-bottom: 15px;
            padding-left: 20px;
        }}
        li {{
            margin-bottom: 5px;
        }}
        hr {{
            border: 0;
            border-top: 1px solid #e2e8f0;
            margin: 30px 0;
        }}
        /* Capa ou cabeçalho inicial */
        .header-container {{
            margin-bottom: 40px;
            text-align: center;
            border-bottom: 3px double #e2e8f0;
            padding-bottom: 25px;
        }}
        .header-container h1 {{
            border: none;
            font-size: 28pt;
            margin-bottom: 10px;
            color: #1e3a8a;
        }}
        .subtitle {{
            font-size: 14pt;
            color: #64748b;
            margin-bottom: 20px;
            font-weight: 400;
        }}
        .metadata {{
            font-size: 10pt;
            color: #94a3b8;
        }}
    </style>
</head>
<body>
    <div class="header-container">
        <h1>{file_info['title']}</h1>
        <div class="subtitle">{file_info['subtitle']}</div>
        <div class="metadata">{file_info['metadata']}</div>
    </div>
    
    <div class="content-body">
        {html_body}
    </div>
</body>
</html>
"""

    print("A guardar ficheiro HTML temporário...")
    with open(temp_html_path, "w", encoding="utf-8") as f:
        f.write(premium_html)

    print("A invocar API do CloudConvert para gerar o PDF...")
    sys.path.append(WORKSPACE_DIR)
    from cloudconvert_service import html_para_pdf
    
    try:
        html_para_pdf(temp_html_path, pdf_path)
        print(f"Sucesso! PDF gerado em: {pdf_path}")
        return True
    except Exception as e:
        print(f"Erro na conversão para PDF de {md_path}: {e}")
        return False
    finally:
        # Limpar ficheiro HTML temporário
        if os.path.exists(temp_html_path):
            os.remove(temp_html_path)
            print("Ficheiro HTML temporário limpo.")

def main():
    success_count = 0
    for file_info in FILES_TO_CONVERT:
        if convert_file(file_info):
            success_count += 1
            
    print(f"\nConversão concluída: {success_count}/{len(FILES_TO_CONVERT)} gerados com sucesso.")

if __name__ == "__main__":
    main()
