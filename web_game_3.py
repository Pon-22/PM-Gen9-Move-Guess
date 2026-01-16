import streamlit as st
import os
import json
import random
import requests
from opencc import OpenCC

# --- 設定頁面資訊 ---
st.set_page_config(page_title="PM Move Guess", page_icon="🎮")

# --- 初始化轉換器 ---
if 'cc' not in st.session_state:
    st.session_state.cc = OpenCC('s2t')
cc = st.session_state.cc

# --- 設定路徑 ---
JSON_FOLDER_PATH = "json_data"        
FULL_CACHE_PATH = "all_moves_cache_3.json"

TOP_N_POKEMON = 200                         
TOP_N_MOVES_POOL = 20                       
CLUES_NUM = 1                               
DISTRACTOR_NUM = 3   

# --- 工具函式 ---
def normalize_name(name):
    return str(name).lower().replace(' ', '-')

# --- 讀取資料 (使用 Cache 加速) ---
@st.cache_data
def load_full_cache():
    """載入全招式快取"""
    if os.path.exists(FULL_CACHE_PATH):
        with open(FULL_CACHE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

@st.cache_data
def load_vgc_data():
    """載入 VGC 資料庫"""
    all_pokemon_data = {} 
    
    if not os.path.exists(JSON_FOLDER_PATH):
        return {}

    try:
        files = [f for f in os.listdir(JSON_FOLDER_PATH) if f.endswith('.json')]
    except:
        return {}

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
                    existing_entry = all_pokemon_data[name]
                    existing_entry['moves'].extend(new_moves)
                    existing_entry['moves'] = list(set(existing_entry['moves']))
                else:
                    all_pokemon_data[name] = {
                        "moves": new_moves,
                        "source": source_name,
                        "rank": current_rank
                    }
        except:
            pass
    return all_pokemon_data

# --- API 與資料處理函式 ---

def get_pokemon_names(name_or_id):
    """
    僅用於取得 ID 與顯示用翻譯 
    (API 請求維持，因為 ID 和圖片需要官方編號)
    """
    url = f"https://pokeapi.co/api/v2/pokemon-species/{name_or_id}"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code != 200: return None, None, None, None
        data = response.json()
        pm_id = data['id'] 
        ja_name, en_name = 'N/A', 'N/A'
        zh_hant, zh_hans = None, None
        for entry in data['names']:
            lang = entry['language']['name']
            if lang == 'en': en_name = entry['name']
            elif lang == 'ja': ja_name = entry['name']
            elif lang == 'zh-Hant': zh_hant = entry['name']
            elif lang == 'zh-Hans': zh_hans = entry['name']
        raw_zh = zh_hant if zh_hant else zh_hans
        final_zh = cc.convert(raw_zh) if raw_zh else 'N/A'
        return pm_id, ja_name, final_zh, en_name
    except:
        return None, None, None, None

def get_random_moves_from_cache(full_db, pokemon_name, excluded_moves, count=3):
    """
    從快取抓干擾招式，並加入「模糊比對」機制解決形態名稱問題
    (例如：VGC 給 'Landorus'，但快取只有 'landorus-incarnate')
    """
    target_key = normalize_name(pokemon_name)
    
    # 1. 第一步：嘗試精準比對
    if target_key in full_db:
        pm_data = full_db[target_key]
    else:
        # 2. 第二步：嘗試模糊比對 (Prefix Match)
        # 找出所有 "landorus-" 開頭的 key (例如 landorus-incarnate)
        # 並且取第一個找到的當作替代品
        found_key = None
        for key in full_db.keys():
            # 加個連字號避免匹配錯誤 (如 mew 匹配到 mewtwo)
            if key.startswith(target_key + "-"):
                found_key = key
                break
        
        if found_key:
            pm_data = full_db[found_key]
        else:
            # 真的完全找不到 (例如資料庫缺漏)
            return []

    # 3. 取得招式池
    all_moves_data = pm_data.get('moves', [])
    
    excluded_set = {normalize_name(m) for m in excluded_moves}
    candidate_moves = []
    
    for move_name in all_moves_data:
        if normalize_name(move_name) not in excluded_set:
            candidate_moves.append(move_name)
            
    actual_count = min(count, len(candidate_moves))
    if actual_count == 0: return []
    
    return random.sample(candidate_moves, actual_count)

def get_move_info(move_name):
    """取得招式的 中文、日文、英文 名稱 (維持 API，因翻譯資料較大未存入快取)"""
    formatted_name = normalize_name(move_name)
    url = f"https://pokeapi.co/api/v2/move/{formatted_name}"
    try:
        response = requests.get(url, timeout=3)
        if response.status_code != 200: return move_name, move_name, move_name 
        data = response.json()
        
        ja_name = None
        en_name = None 
        zh_hant, zh_hans = None, None
        
        for entry in data['names']:
            lang = entry['language']['name']
            if lang == 'ja': ja_name = entry['name']
            elif lang == 'en': en_name = entry['name'] 
            elif lang == 'zh-Hant': zh_hant = entry['name']
            elif lang == 'zh-Hans': zh_hans = entry['name']
            
        raw_zh = zh_hant if zh_hant else zh_hans
        final_zh = cc.convert(raw_zh) if raw_zh else move_name
        final_ja = ja_name if ja_name else move_name
        final_en = en_name if en_name else move_name
        
        return final_zh, final_ja, final_en
    except:
        return move_name, move_name, move_name

def find_other_matches(full_db, quiz_moves, current_answer_en_name):
    """反向搜尋：回傳 中 | 日 | 英"""
    if not full_db: return []
    quiz_moves_set = {normalize_name(m) for m in quiz_moves}
    matches = []
    for pm_key, pm_data in full_db.items():
        if pm_key.lower() == current_answer_en_name.lower(): continue
        pm_moves_set = set(pm_data['moves'])
        if quiz_moves_set.issubset(pm_moves_set):
            names = pm_data.get('names', {})
            zh = names.get('zh', pm_key)
            ja = names.get('ja', 'N/A')
            en = names.get('en', pm_key)
            matches.append(f"{zh} | {ja} | {en}")
    return matches

def generate_new_question(vgc_db, full_db):
    """產生題目並存入 session_state"""
    if not vgc_db:
        st.error("資料庫為空")
        return

    target_pm_name = random.choice(list(vgc_db.keys()))
    pm_data = vgc_db[target_pm_name]
    move_pool = pm_data['moves']
    
    id, jpn, chn, enn = get_pokemon_names(target_pm_name)
    
    # 避免 API 失敗
    if id is None:
        # 如果 API 失敗，重試一次 (需注意遞迴深度，但在這裡通常沒事)
        return generate_new_question(vgc_db, full_db)

    if len(move_pool) < CLUES_NUM: vgc_moves = move_pool
    else: vgc_moves = random.sample(move_pool, CLUES_NUM)
    
    # --- 修改這裡：使用 Cache 版的隨機招式 ---
    random_fillers = get_random_moves_from_cache(full_db, target_pm_name, vgc_moves, count=DISTRACTOR_NUM)
    
    final_move_list = []
    seen_moves = set()
    raw_list = vgc_moves + random_fillers
    for move in raw_list:
        norm = normalize_name(move)
        if norm not in seen_moves:
            final_move_list.append(move)
            seen_moves.add(norm)
    random.shuffle(final_move_list)
    
    # 翻譯招式
    translated_moves = []
    for m in final_move_list:
        z, j, e = get_move_info(m)
        translated_moves.append(f"**{z}**\n\n{j}\n\n*{e}*") 

    # 存入 Session State
    st.session_state.current_q = {
        "moves_display": translated_moves,
        "moves_raw": final_move_list,
        "answer_name": chn,
        "answer_jp": jpn,
        "answer_en": enn,
        "answer_id": id,
        "target_pm_name": target_pm_name,
        "source": pm_data['source'],
        "rank": pm_data['rank']
    }
    st.session_state.show_answer = False

# --- 主程式 UI ---

st.title("GEN 9 PM Move Guess")

# 1. 載入資料
full_db = load_full_cache()
vgc_db = load_vgc_data()

if not full_db:
    st.warning("⚠️ 找不到全招式快取，反向搜尋與隨機招式功能將受限。")
if not vgc_db:
    st.error("❌ 找不到 VGC JSON 資料，請檢查路徑設定。")
    st.stop()

# 2. 初始化題目 (傳入 full_db)
if 'current_q' not in st.session_state:
    generate_new_question(vgc_db, full_db)

# 3. 顯示按鈕區
col1, col2 = st.columns([1, 1])
with col1:
    if st.button("🔄 下一題", use_container_width=True):
        generate_new_question(vgc_db, full_db) # 這裡也要傳入 full_db
        st.rerun()

with col2:
    if st.button("👁️ 看答案", use_container_width=True):
        st.session_state.show_answer = True
        st.rerun()

# 4. 顯示題目 (招式)
q = st.session_state.current_q
if q:
    st.subheader("這隻寶可夢會使用：")
    
    # 用 4 個欄位顯示招式
    m_cols = st.columns(4)
    for i, move_text in enumerate(q['moves_display']):
        with m_cols[i % 4]:
            st.info(move_text)

    # 5. 顯示答案區
    if st.session_state.show_answer:
        st.divider()
        st.success(f"### 答案：{q['answer_name']} ({q['answer_jp']})")
        st.caption(f"英文: {q['answer_en']} | ID: #{q['answer_id']}")
        st.write(f"📊 **來源紀錄**: `{q['source']}` (Rank: #{q['rank']})")
        
        img_url = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{q['answer_id']}.png"
        st.image(img_url, width=200)

        # 反向搜尋 (撞招檢查)
        with st.spinner("正在檢查是否有其他寶可夢會這四招..."):
            others = find_other_matches(full_db, q['moves_raw'], q['target_pm_name'])
        
        if others:
            st.warning(f"還有{len(others)}隻PM也會這組配招：")
            # 顯示列表
            for o in others:
                st.write(f"- {o}")
        else:
            st.balloons() 
            st.info("唯一解")