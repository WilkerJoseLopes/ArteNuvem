import os
import requests
import cloudconvert

# =========================
# CONFIGURAÇÃO
# =========================

API_KEY = os.getenv("CLOUDCONVERT_API_KEY")

if not API_KEY:
    raise RuntimeError(
        "CLOUDCONVERT_API_KEY não definida nas variáveis de ambiente"
    )

cloudconvert.configure(
    api_key=API_KEY,
    sandbox=False  # True só se estiveres no modo sandbox
)

# =========================
# FUNÇÃO PRINCIPAL
# =========================

def html_para_pdf(html_path: str, pdf_path: str) -> str:
    """
    Converte um ficheiro HTML local para PDF usando CloudConvert
    """

    # 1. Criar Job
    job = cloudconvert.Job.create(payload={
        "tasks": {
            "import_html": {
                "operation": "import/upload"
            },
            "convert_pdf": {
                "operation": "convert",
                "input": "import_html",
                "input_format": "html",
                "output_format": "pdf",
                "engine": "chrome",
                "print_background": True
            },
            "export_pdf": {
                "operation": "export/url",
                "input": "convert_pdf"
            }
        }
    })

    # 2. Obter task de upload
    import_task = next(
        task for task in job["tasks"]
        if task["name"] == "import_html"
    )

    # 3. Upload do HTML
    with open(html_path, "rb") as f:
        cloudconvert.Task.upload(import_task, f)

    # 4. Esperar conclusão do Job
    job = cloudconvert.Job.wait(job["id"])

    # 5. Obter URL do PDF
    export_task = next(
        task for task in job["tasks"]
        if task["name"] == "export_pdf"
    )

    file_url = export_task["result"]["files"][0]["url"]

    # 6. Download do PDF
    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)

    response = requests.get(file_url)
    response.raise_for_status()

    with open(pdf_path, "wb") as f:
        f.write(response.content)

    return pdf_path


# =========================
# TESTE DIRETO
# =========================

if __name__ == "__main__":
    html_file = "teste.html"
    pdf_file = "output/teste.pdf"

    resultado = html_para_pdf(html_file, pdf_file)
    print(f"✅ PDF gerado com sucesso: {resultado}")
