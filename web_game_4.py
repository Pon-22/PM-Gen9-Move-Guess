import streamlit as st
import os
import json
import random
import requests
from opencc import OpenCC
import time

# --- 設定頁面資訊 ---
st.set_page_config(page_title="GEN 9 PM Move Guess", page_icon="🎮", layout="centered")

# --- 設定路徑 ---
JSON_FOLDER_PATH = "json_data"
CACHE_PATH_MOVES = "all_moves_cache_3.json"
CACHE_PATH_STATS = "all_moves_cache_4.json"

TOP_N_POKEMON = 200                         
TOP_N_MOVES_POOL = 20                       
CLUES_NUM = 1                               
DISTRACTOR_NUM = 3   
BANNED_MOVES = {"protect", "tera-blast", "substitute", "rest", "sleep-talk", "endure", "facade", "helping-hand"}

# --- 初始化轉換器 ---
if 'cc' not in st.session_state:
    st.session_state.cc = OpenCC('s2t')
cc = st.session_state.cc

# ==========================================
# ★★★ 核心修改：多人連線共享狀態 ★★★
# ==========================================

class GameServer:
    def __init__(self):
        # 這是公共佈告欄，存著現在的題目
        self.current_q_move = None  # 配招題的題目
        self.current_q_stat = None  # 種族值題的題目
        self.last_update_time = time.time()

# 使用 cache_resource 確保這個物件在所有使用者的連線中是「共用」的
@st.cache_resource
def get_server_state():
    return GameServer()

server = get_server_state()

# ==========================================
# 資料讀取與工具函式 (維持原樣)
# ==========================================
def normalize_name(name):
    return str(name).lower().replace(' ', '-')

@st.cache_data
def load_vgc_data():
    all_pokemon_data = {} 
    if not os.path.exists(JSON_FOLDER_PATH): return {}
    try:
        files = [f for f in os.listdir(JSON_FOLDER_PATH) if f.endswith('.json')]
    except: return {}
    files.sort(reverse=True) 
    for file_name in files:
        file_path = os.path.join(JSON_FOLDER_PATH, file_name)
        source_name = file_name.replace('.json', '').replace('_FULL', '')
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            top_list = data[:TOP_N_POKEMON]
            for rank_index, pm in enumerate(top_list):
                current_rank = rank_index + 1
                name = pm.get('name')
                raw_moves = pm.get('moves', [])
                valid_moves = [m['move'] for m in raw_moves if m.get('move') != "Other"]
                new_moves = valid_moves[:TOP_N_MOVES_POOL]
                if name in all_pokemon_data:
                    all_pokemon_data[name]['moves'].extend(new_moves)
                    all_pokemon_data[name]['moves'] = list(set(all_pokemon_data[name]['moves']))
                else:
                    all_pokemon_data[name] = {"moves": new_moves, "source": source_name, "rank": current_rank}
        except: pass
    return all_pokemon_data

@st.cache_data
def load_move_cache():
    if os.path.exists(CACHE_PATH_MOVES):
        with open(CACHE_PATH_MOVES, 'r', encoding='utf-8') as f: return json.load(f)
    return {}

@st.cache_data
def load_stat_cache():
    if os.path.exists(CACHE_PATH_STATS):
        with open(CACHE_PATH_STATS, 'r', encoding='utf-8') as f: return json.load(f)
    return {}

def get_pokemon_names_api(name_or_id):
    url = f"https://pokeapi.co/api/v2/pokemon-species/{name_or_id}"
    try:
        response = requests.get(url, timeout=3)
        if response.status_code != 200: return None, None, None, None
        data = response.json()
        pm_id = data['id'] 
        ja, en = 'N/A', 'N/A'
        zh_hant, zh_hans = None, None
        for entry in data['names']:
            lang = entry['language']['name']
            if lang == 'en': en = entry['name']
            elif lang == 'ja': ja = entry['name']
            elif lang == 'zh-Hant': zh_hant = entry['name']
            elif lang == 'zh-Hans': zh_hans = entry['name']
        raw_zh = zh_hant if zh_hant else zh_hans
        final_zh = cc.convert(raw_zh) if raw_zh else 'N/A'
        return pm_id, ja, final_zh, en
    except: return None, None, None, None

def get_move_info(move_name):
    formatted_name = normalize_name(move_name)
    url = f"https://pokeapi.co/api/v2/move/{formatted_name}"
    try:
        response = requests.get(url, timeout=3)
        if response.status_code != 200: return move_name, move_name, move_name 
        data = response.json()
        ja, en, zh_hant, zh_hans = None, None, None, None
        for entry in data['names']:
            lang = entry['language']['name']
            if lang == 'ja': ja = entry['name']
            elif lang == 'en': en = entry['name'] 
            elif lang == 'zh-Hant': zh_hant = entry['name']
            elif lang == 'zh-Hans': zh_hans = entry['name']
        raw_zh = zh_hant if zh_hant else zh_hans
        final_zh = cc.convert(raw_zh) if raw_zh else move_name
        final_zh = final_zh.replace('巖', '岩')
        return final_zh, ja or move_name, en or move_name
    except: return move_name, move_name, move_name

def get_random_moves_from_cache(full_db, pokemon_name, excluded_moves, count=3):
    target_key = normalize_name(pokemon_name)
    if target_key in full_db: pm_data = full_db[target_key]
    else:
        found_key = None
        for key in full_db.keys():
            if key.startswith(target_key + "-"):
                found_key = key
                break
        if found_key: pm_data = full_db[found_key]
        else: return []
    all_moves_data = pm_data.get('moves', [])
    excluded_set = {normalize_name(m) for m in excluded_moves}
    candidate_moves = []
    for move_name in all_moves_data:
        norm_move = normalize_name(move_name)
        if norm_move not in excluded_set and norm_move not in BANNED_MOVES:
            candidate_moves.append(move_name)
    actual_count = min(count, len(candidate_moves))
    if actual_count == 0: return []
    return random.sample(candidate_moves, actual_count)

def find_other_matches(full_db, quiz_moves, current_answer_en_name):
    if not full_db: return []
    quiz_moves_set = {normalize_name(m) for m in quiz_moves}
    matches = []
    for pm_key, pm_data in full_db.items():
        if pm_key.lower() == current_answer_en_name.lower(): continue
        pm_moves_set = set(pm_data['moves'])
        if quiz_moves_set.issubset(pm_moves_set):
            names = pm_data.get('names', {})
            matches.append(f"{names.get('zh', pm_key)} | {names.get('ja', 'N/A')} | {names.get('en', pm_key)}")
    return matches

def get_pokemon_id(name_or_id):
    url = f"https://pokeapi.co/api/v2/pokemon-species/{name_or_id}"
    try:
        response = requests.get(url, timeout=3)
        if response.status_code == 200: return response.json()['id']
    except: return None
    return None

# ==========================================
# 題目生成 (修改版：支援寫入 Server State)
# ==========================================

def generate_move_question(vgc_db, move_cache, is_admin=False):
    """產生配招題目"""
    if not vgc_db: return
    
    # 邏輯：如果你是裁判(Admin)，你負責產生新題目並寫入佈告欄
    # 如果你是選手，你只是去佈告欄抄題目，自己不能產生
    
    target_pm_name = random.choice(list(vgc_db.keys()))
    pm_data = vgc_db[target_pm_name]
    raw_move_pool = pm_data['moves']
    
    valid_vgc_pool = [m for m in raw_move_pool if normalize_name(m) not in BANNED_MOVES]
    if not valid_vgc_pool: valid_vgc_pool = raw_move_pool
    id, jpn, chn, enn = get_pokemon_names_api(target_pm_name)
    if id is None: return generate_move_question(vgc_db, move_cache, is_admin)
    if len(valid_vgc_pool) < CLUES_NUM: vgc_moves = valid_vgc_pool
    else: vgc_moves = random.sample(valid_vgc_pool, CLUES_NUM)
    random_fillers = get_random_moves_from_cache(move_cache, target_pm_name, vgc_moves, count=DISTRACTOR_NUM)
    final_move_list = []
    seen = set()
    for m in (vgc_moves + random_fillers):
        norm = normalize_name(m)
        if norm not in seen:
            final_move_list.append(m)
            seen.add(norm)
    random.shuffle(final_move_list)
    translated_moves = []
    for m in final_move_list:
        z, j, e = get_move_info(m)
        translated_moves.append(f"**{z}**\n\n{j}\n\n*{e}*") 

    new_q = {
        "moves_display": translated_moves,
        "moves_raw": final_move_list,
        "answer_name": chn, "answer_jp": jpn, "answer_en": enn, "answer_id": id,
        "target_pm_name": target_pm_name, "source": pm_data['source'], "rank": pm_data['rank']
    }
    
    # ★★★ 寫入公共佈告欄 ★★★
    server.current_q_move = new_q
    server.last_update_time = time.time()
    return new_q

def generate_stat_question(vgc_db, stat_cache, is_admin=False):
    """產生種族值題目"""
    if not vgc_db: return
    target_pm_name = random.choice(list(vgc_db.keys()))
    pm_data_vgc = vgc_db[target_pm_name]
    target_key = normalize_name(target_pm_name)
    pm_cache_data = None
    if target_key in stat_cache: pm_cache_data = stat_cache[target_key]
    else:
        for key in stat_cache.keys():
            if key.startswith(target_key + "-"):
                pm_cache_data = stat_cache[key]
                break
    if not pm_cache_data: return generate_stat_question(vgc_db, stat_cache, is_admin)
    stats = pm_cache_data.get('stats', {})
    names = pm_cache_data.get('names', {})
    pm_id = get_pokemon_id(target_pm_name)
    if not pm_id: return generate_stat_question(vgc_db, stat_cache, is_admin)

    new_q = {
        "stats": stats,
        "answer_name": names.get('zh', target_pm_name),
        "answer_jp": names.get('ja', 'N/A'),
        "answer_en": names.get('en', target_pm_name),
        "answer_id": pm_id,
        "source": pm_data_vgc['source'], "rank": pm_data_vgc['rank']
    }
    
    # ★★★ 寫入公共佈告欄 ★★★
    server.current_q_stat = new_q
    server.last_update_time = time.time()
    return new_q

# ==========================================
# 主程式 UI
# ==========================================

vgc_db = load_vgc_data()
if not vgc_db:
    st.error("❌ 找不到 VGC JSON 資料。")
    st.stop()

# --- 側邊欄：權限設定 ---
st.sidebar.title("Setting")
is_admin = st.sidebar.toggle("Host", value=False)

admin_input = st.sidebar.text_input("password", type="password")
ADMIN_PASSWORD = "bobohost"

is_admin = False
if admin_input == ADMIN_PASSWORD:
    is_admin = True
    st.sidebar.success("你負責出題，並可以看到答案")
else:
    if admin_input: # 如果有輸入但錯誤
        st.sidebar.error("❌ 密碼錯誤")
    else:
        st.sidebar.info("👤 目前身分：選手")

tab1, tab2 = st.tabs(["move guess", "base stats guess"])

# ==========================================
# 分頁 1: 猜配招
# ==========================================
with tab1:
    move_cache = load_move_cache()
    
    # 檢查是否需要初始化 (如果是選手，就先讀 Server 的)
    if 'current_q' not in st.session_state:
        if server.current_q_move:
             st.session_state.current_q = server.current_q_move
        elif is_admin: # 如果 Server 是空的且我是裁判，我先出一題
             st.session_state.current_q = generate_move_question(vgc_db, move_cache, is_admin=True)

    # 顯示按鈕區
    col1, col2 = st.columns([1, 1])
    with col1:
        if is_admin:
            # 裁判按鈕：產生新題目並推送到 Server
            if st.button("🔄 下一題", use_container_width=True, type="primary"):
                q = generate_move_question(vgc_db, move_cache, is_admin=True)
                st.session_state.current_q = q
                st.rerun()
        else:
            if st.button("🎲 下一題 (自己玩)", use_container_width=True):
                q = generate_move_question(vgc_db, move_cache, is_admin=False)
                st.session_state.current_q = q
                st.session_state.show_answer = False
                st.rerun()
            # 選手按鈕：去 Server 抓題目
            if st.button("📥 同步題目", use_container_width=True):
                if server.current_q_move:
                    st.session_state.current_q = server.current_q_move
                    st.session_state.show_answer = False # 同步時先把答案蓋起來
                    st.success("已同步裁判的題目！")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.warning("裁判還沒出題喔！")

    with col2:
        # 看答案按鈕
        if st.button("👁️ 看答案", use_container_width=True):
            st.session_state.show_answer = True
            st.rerun()

    # 顯示題目
    q = st.session_state.get('current_q')
    if q:
        st.subheader("這隻寶可夢會使用：")
        m_cols = st.columns(4)
        for i, move_text in enumerate(q['moves_display']):
            with m_cols[i % 4]: st.info(move_text)

        # 顯示答案邏輯：
        # 1. 裁判永遠看得到答案區 (但可以選擇要不要按開)
        # 2. 選手只有在自己按了「看答案」後才看得到
        # 3. 為了方便裁判，我們可以在這直接顯示小抄
        
        if is_admin:
            st.caption(f"答案是 **{q['answer_name']}**")

        if st.session_state.get('show_answer', False):
            st.divider()
            st.success(f"### 答案：{q['answer_name']} ({q['answer_jp']})")
            st.caption(f"英文: {q['answer_en']} | ID: #{q['answer_id']}")
            st.write(f"📊 **來源紀錄**: `{q['source']}` (Rank: #{q['rank']})")
            img_url = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{q['answer_id']}.png"
            st.image(img_url, width=200)

            with st.spinner("正在檢查是否有其他寶可夢會這四招..."):
                others = find_other_matches(move_cache, q['moves_raw'], q['target_pm_name'])
            if others:
                st.warning(f"還有 {len(others)} 隻PM也會這組配招：")
                for o in others: st.write(f"- {o}")
            else:
                st.balloons() 
                st.info("唯一解 (Unique)")

# ==========================================
# 分頁 2: 猜種族值
# ==========================================
with tab2:
    stat_cache = load_stat_cache()
    if not stat_cache:
        st.warning("⚠️ 找不到 Cache 4")
    else:
        # 狀態同步邏輯
        if 'current_stat_q' not in st.session_state:
            if server.current_q_stat:
                 st.session_state.current_stat_q = server.current_q_stat
            elif is_admin:
                 st.session_state.current_stat_q = generate_stat_question(vgc_db, stat_cache, is_admin=True)

        scol1, scol2 = st.columns([1, 1])
        with scol1:
            if is_admin:
                if st.button("🔄 下一題", key="stat_next", use_container_width=True, type="primary"):
                    q = generate_stat_question(vgc_db, stat_cache, is_admin=True)
                    st.session_state.current_stat_q = q
                    st.rerun()
            else:
                if st.button("🎲 下一題 (自己玩)", key="stat_next_self", use_container_width=True):
                    q = generate_stat_question(vgc_db, stat_cache, is_admin=False)
                    st.session_state.current_stat_q = q
                    st.session_s
                if st.button("📥 同步題目", key="stat_sync", use_container_width=True):
                    if server.current_q_stat:
                        st.session_state.current_stat_q = server.current_q_stat
                        st.session_state.stat_show_answer = False
                        st.success("已同步！")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.warning("裁判還沒出題！")
        with scol2:
            if st.button("👁️ 看答案 ", key="stat_ans", use_container_width=True):
                st.session_state.stat_show_answer = True
                st.rerun()

        sq = st.session_state.get('current_stat_q')
        if sq:
            st.subheader("請根據種族值猜寶可夢：")
            stats = sq['stats']
            row1 = st.columns(3)
            row1[0].metric("HP", stats.get('hp', 0))
            row1[1].metric("Attack", stats.get('atk', 0))
            row1[2].metric("Defense", stats.get('def', 0))
            row2 = st.columns(3)
            row2[0].metric("Sp. Atk", stats.get('spa', 0))
            row2[1].metric("Sp. Def", stats.get('spd', 0))
            row2[2].metric("Speed", stats.get('spe', 0))
            st.caption(f"種族值總和 (BST): {sum(stats.values())}")

            if is_admin:
                st.caption(f"答案是 **{sq['answer_name']}**")

            if st.session_state.get('stat_show_answer', False):
                st.divider()
                st.success(f"### 答案：{sq['answer_name']} ({sq['answer_jp']})")
                st.caption(f"英文: {sq['answer_en']} | ID: #{sq['answer_id']}")
                st.write(f"📊 **來源紀錄**: `{sq['source']}` (Rank: #{sq['rank']})")
                img_url = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{sq['answer_id']}.png"
                st.image(img_url, width=200)
                st.balloons()