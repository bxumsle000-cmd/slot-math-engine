"""
password.py - 密碼雜湊工具

使用 bcrypt 對密碼做單向雜湊，兩個路由都需要（players 建立、auth 驗證），
集中在此避免重複定義雜湊邏輯。

【為什麼不直接存明文密碼？】
若 DB 被盜，攻擊者直接拿到所有人的密碼。
雜湊後即使 DB 被盜，也只拿到無法反推的雜湊值。

【什麼是鹽值（salt）？】
每次雜湊前 bcrypt 會產生一段隨機字串（鹽值），和密碼混在一起計算。
同一個密碼每次雜湊結果都不同，讓攻擊者無法用預先算好的對照表破解。

【鹽值存在哪裡？】
bcrypt 把鹽值直接內嵌在雜湊結果字串裡：
    "$2b$12$K9mXXX...（鹽值）...xQ7pL...（雜湊結果）"
存進 DB 的就是這整串，不需要另外存鹽值。

【驗證密碼的流程（checkpw）】
1. 從 DB 取出整串雜湊字串
2. checkpw 自動從字串裡拆出鹽值
3. 用同一個鹽值對使用者輸入的密碼重新計算雜湊
4. 比對結果是否相同 → 回傳 True / False
"""

import bcrypt


def hash_password(plain: str) -> str:  # 將明文密碼雜湊成 bcrypt 字串
    """
    將明文密碼做 bcrypt 雜湊，回傳可安全存入 DB 的字串。

    Args:
        plain: 使用者輸入的明文密碼

    Returns:
        bcrypt 雜湊字串（含鹽值，格式如 $2b$12$...）
    """
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:  # 驗證明文密碼是否符合雜湊值
    """
    驗證明文密碼與 DB 中的 bcrypt 雜湊是否吻合。

    Args:
        plain:  使用者輸入的明文密碼
        hashed: DB 中儲存的 bcrypt 雜湊字串

    Returns:
        True 表示密碼正確，False 表示錯誤
    """
    return bcrypt.checkpw(plain.encode(), hashed.encode())
