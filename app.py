import os
import hashlib
import secrets
import sqlite3
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
import re

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

DB_FILE = 'leilao.db'
UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

TOKENS_ADMIN = {}
TOKENS_CLIENTES = {}

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn
@app.route('/veiculo/<int:id>')
def pagina_veiculo(id):
    return send_from_directory('static', 'veiculo.html')
def init_db():
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS admins (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, senha_hash TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS clientes (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, email TEXT UNIQUE NOT NULL, cpf TEXT NOT NULL, telefone TEXT NOT NULL, senha_hash TEXT NOT NULL, criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # TABELA DE VEÍCULOS ATUALIZADA COM OS CAMPOS DA COPART
    c.execute('''CREATE TABLE IF NOT EXISTS veiculos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, lote TEXT UNIQUE NOT NULL, marca TEXT, modelo TEXT, versao TEXT, 
        ano_fab INTEGER, ano_mod INTEGER, status TEXT DEFAULT 'Disponível', doc TEXT, condicao TEXT, 
        chassi TEXT, placa TEXT, km INTEGER, cor TEXT, combustivel TEXT, lance_atual REAL, valor_fipe REAL, 
        patio TEXT, categoria TEXT, foto_url TEXT, destaque INTEGER DEFAULT 0, criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
    c.execute('''CREATE TABLE IF NOT EXISTS lances (id INTEGER PRIMARY KEY AUTOINCREMENT, veiculo_id INTEGER, cliente_id INTEGER, nome_cliente TEXT, telefone_cliente TEXT, cpf_cliente TEXT, valor_lance REAL, data_lance TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS vendas (id INTEGER PRIMARY KEY AUTOINCREMENT, nome_cliente TEXT, telefone_cliente TEXT, marca TEXT, modelo TEXT, ano INTEGER, condicao TEXT, valor_pretendido REAL, data_venda TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS config (chave TEXT PRIMARY KEY, valor TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS leiloes (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT, hora TEXT, local TEXT, link TEXT, criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    conn.commit()
    
    c.execute("INSERT OR IGNORE INTO config (chave, valor) VALUES ('suporte_email', 'suporte@copart.com.br')")
    c.execute("INSERT OR IGNORE INTO config (chave, valor) VALUES ('suporte_telefone', '(41) 3333-4444')")
    c.execute("INSERT OR IGNORE INTO config (chave, valor) VALUES ('suporte_horario', 'Segunda a Sexta, das 08h às 18h')")
    
    c.execute('SELECT COUNT(*) FROM admins')
    if c.fetchone()[0] == 0:
        c.execute('INSERT INTO admins (username, senha_hash) VALUES (?, ?)', ('admin', hashlib.sha256('admin123'.encode()).hexdigest()))
        conn.commit()
    c.close()
    conn.close()

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token or token not in TOKENS_ADMIN:
            return jsonify({'erro': 'Acesso negado.'}), 401
        return f(*args, **kwargs)
    return decorated

def cliente_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token or token not in TOKENS_CLIENTES:
            return jsonify({'erro': 'Sessão expirada. Faça login novamente.'}), 401
        return f(*args, **kwargs)
    return decorated

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json() or {}
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM admins WHERE username = ?', (data.get('username'),))
    admin = c.fetchone()
    c.close()
    conn.close()
    if not admin or admin['senha_hash'] != hashlib.sha256(data.get('senha','').encode()).hexdigest():
        return jsonify({'erro': 'Usuário ou senha incorretos'}), 401
    token = secrets.token_urlsafe(32)
    TOKENS_ADMIN[token] = data.get('username')
    return jsonify({'token': token})

@app.route('/api/admin/veiculos', methods=['POST'])
@admin_required
def criar_veiculo():
    foto_url = ''
    if 'foto' in request.files:
        file = request.files['foto']
        if file.filename != '':
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            foto_url = f"/uploads/{filename}"
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute('''INSERT INTO veiculos (lote, marca, modelo, versao, ano_fab, ano_mod, status, condicao, chassi, placa, km, cor, combustivel, lance_atual, valor_fipe, patio, categoria, foto_url, destaque) 
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (request.form.get('lote'), request.form.get('marca'), request.form.get('modelo'), request.form.get('versao'),
                   request.form.get('ano_fab'), request.form.get('ano_mod'), request.form.get('status'), request.form.get('condicao'), 
                   request.form.get('chassi'), request.form.get('placa'), request.form.get('km'), request.form.get('cor'), 
                   request.form.get('combustivel'), request.form.get('lance_atual'), request.form.get('valor_fipe'), 
                   request.form.get('patio'), request.form.get('categoria'), foto_url, 1 if request.form.get('destaque') == 'true' else 0))
        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({'erro': 'Erro ao cadastrar. Lote duplicado?'}), 400
    finally:
        c.close()
        conn.close()
    return jsonify({'ok': True})

# ... (mantenha as outras rotas de editar, lances, vendas como estavam) ...

@app.route('/api/admin/ler-ficha', methods=['POST'])
@admin_required
def ler_ficha():
    if 'imagem' not in request.files:
        return jsonify({'erro': 'Nenhuma imagem enviada'}), 400
    
    file = request.files['imagem']
    temp_path = os.path.join(app.config['UPLOAD_FOLDER'], 'temp_ficha.jpg')
    file.save(temp_path)

    try:
        img = Image.open(temp_path)
        img = ImageOps.invert(img.convert('RGB'))
        img.save(temp_path)

        texto = pytesseract.image_to_string(Image.open(temp_path), lang='por')
        dados = {}
        
        # PADRÕES EXATOS DA FICHA DA COPART
        match_marca = re.search(r'Marca:\s*([A-Za-z]+)', texto, re.IGNORECASE)
        if match_marca: dados['marca'] = match_marca.group(1).strip()

        match_modelo = re.search(r'Modelo:\s*([A-Za-z0-9]+)', texto, re.IGNORECASE)
        if match_modelo: dados['modelo'] = match_modelo.group(1).strip()

        match_versao = re.search(r'Versão:\s*(.*?)(?:\n|Ano)', texto, re.IGNORECASE)
        if match_versao: dados['versao'] = match_versao.group(1).strip()

        match_ano_fab = re.search(r'Ano de Fabricação:\s*(20\d{2})', texto, re.IGNORECASE)
        if match_ano_fab: dados['ano_fab'] = match_ano_fab.group(1)

        match_ano_mod = re.search(r'Ano Modelo:\s*(20\d{2})', texto, re.IGNORECASE)
        if match_ano_mod: dados['ano_mod'] = match_ano_mod.group(1)

        match_chassi = re.search(r'Chassi:\s*([A-Za-z0-9]+)', texto, re.IGNORECASE)
        if match_chassi: dados['chassi'] = match_chassi.group(1).strip()

        match_combustivel = re.search(r'Combustível:\s*([A-Za-z0-9/]+)', texto, re.IGNORECASE)
        if match_combustivel: dados['combustivel'] = match_combustivel.group(1).strip()

        os.remove(temp_path)
        return jsonify({'ok': True, 'dados': dados, 'texto_bruto': texto})
        
    except Exception as e:
        return jsonify({'ok': True, 'dados': {}, 'texto_bruto': f"ERRO: {str(e)}"})

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/admin')
def admin_page():
    return send_from_directory('static', 'admin.html')

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f'🚀 Servidor rodando em http://localhost:{port}')
    app.run(host='0.0.0.0', port=port)