# 🎨 ArteNuvem

ArteNuvem é uma plataforma web para partilha, visualização e curadoria de imagens artísticas, desenvolvida no contexto da unidade curricular **Computação na Nuvem**.

O sistema permite que utilizadores publiquem imagens, interajam através de likes e comentários, participem em exposições virtuais e explorem conteúdos organizados por categorias.

## 🚀 Funcionalidades Principais

- Upload e visualização de imagens
- Sistema de likes e comentários
- Exposições virtuais com ranking Top 10 por popularidade
- Pesquisa e filtragem por categorias
- Área administrativa para gestão de categorias e exposições
- Exportação de exposições em PDF
- Autenticação de utilizadores via Google

## 🧱 Tecnologias Utilizadas

- **Back-end:** Python, Flask, SQLAlchemy
- **Base de Dados:** PostgreSQL
- **Front-end:** HTML, CSS, Jinja2
- **Armazenamento:** Supabase Storage
- **Autenticação:** Google OAuth
- **Deploy:** Render
- **API:** REST (JSON)

## 🌐 Arquitetura

A aplicação segue uma arquitetura cliente-servidor, com separação entre:

- Camada de apresentação (Front-end)
- Camada de lógica de negócio (Flask)
- Camada de dados (PostgreSQL)

Inclui Web Services REST para acesso aos principais recursos da plataforma.

## 🎓 Contexto Académico

Este projeto foi desenvolvido como trabalho prático para a unidade curricular **Computação na Nuvem**, com foco em:

- Serviços cloud
- Programação distribuída
- APIs REST
- Segurança e escalabilidade

## 🔑⚠️ Chaves API
Todas as chaves de API como do google auth, CloudConvert e entre outros, estão guardados no render e são chamados por variaveis que tem as chaves armazenadas, variaveis essas que estão presentes no codigo.


## 👤 Colaboradores do Projeto
- Danilson Gonçalves
- Wilker Lopes
