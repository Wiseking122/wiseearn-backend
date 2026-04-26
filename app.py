from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import datetime

app = Flask(__name__)
CORS(app)  # Required for Mini App to call your backend

BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"  # 👈 Replace
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# --- In-memory storage (replace with database later) ---
user_balances = {}
user_ads = {}
user_surveys = {}
user_withdrawals = {}
user_streaks = {}
user_last_claim = {}
user_challenges = {}
user_referrals = {}      # {user_id: [referred_user_ids]}
user_ref_earned = {}     # {user_id: total_pts_from_refs}

# ──────────────────────────────────────────────────────
#  Telegram Webhook
# ──────────────────────────────────────────────────────
@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.json
    if "message" in update:
        chat_id = update["message"]["chat"]["id"]
        text = update["message"].get("text", "")

        if text.startswith("/start"):
            args = text.split(" ")
            if len(args) > 1:
                arg = args[1]
                if arg.startswith("reward_"):
                    add_points(chat_id, 10)
                    user_ads[chat_id] = user_ads.get(chat_id, 0) + 1
                    send_message(chat_id, "🎉 Ad completed! +10 points credited.")
                elif arg.startswith("survey_"):
                    add_points(chat_id, 50)
                    user_surveys[chat_id] = user_surveys.get(chat_id, 0) + 1
                    send_message(chat_id, "📝 Survey completed! +50 points credited.")
                elif arg.startswith("ref_"):
                    referrer_id = int(arg.replace("ref_", ""))
                    if referrer_id != chat_id:
                        add_points(referrer_id, 100)
                        # Track referral
                        if referrer_id not in user_referrals:
                            user_referrals[referrer_id] = []
                        if chat_id not in user_referrals[referrer_id]:
                            user_referrals[referrer_id].append(chat_id)
                            user_ref_earned[referrer_id] = user_ref_earned.get(referrer_id, 0) + 100
                            # Check milestones
                            ref_count = len(user_referrals[referrer_id])
                            milestones = {1:50, 5:200, 10:500, 25:1500, 50:3000, 100:10000}
                            if ref_count in milestones:
                                bonus = milestones[ref_count]
                                add_points(referrer_id, bonus)
                                send_message(referrer_id, f"🎉 Milestone! {ref_count} referrals → +{bonus} bonus points!")
                        send_message(referrer_id, f"👥 New referral! +100 points. Total referrals: {len(user_referrals[referrer_id])}")
                    add_points(chat_id, 100)
                    send_message(chat_id, "🎉 Welcome to WiseEarn! You got +100 bonus points for joining via referral!")
                    send_mini_app_button(chat_id)
                else:
                    send_mini_app_button(chat_id)
            else:
                send_mini_app_button(chat_id)

        elif text == "/balance":
            balance = user_balances.get(chat_id, 0)
            send_message(chat_id, f"💰 Your balance: {balance} points (≈ ${balance/100:.2f})")

        elif text == "/withdraw":
            send_message(chat_id, "🏦 Open the WiseEarn app to request a withdrawal.")
            send_mini_app_button(chat_id)

        elif text == "/bonus":
            claim_bonus(chat_id)

        elif text == "/challenge":
            progress = user_challenges.get(chat_id, 0)
            send_message(chat_id, f"🔥 Daily challenge: {progress}/5 tasks completed")

        elif text == "/app" or text == "/open":
            send_mini_app_button(chat_id)

    return "OK"

# ──────────────────────────────────────────────────────
#  Mini App API Endpoints
# ──────────────────────────────────────────────────────

@app.route('/balance', methods=['GET'])
def get_balance():
    """Called by Mini App to load user data"""
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"error": "No user_id"}), 400
    uid = int(user_id)
    return jsonify({
        "balance": user_balances.get(uid, 0),
        "ads":     user_ads.get(uid, 0),
        "surveys": user_surveys.get(uid, 0),
        "streak":  _get_streak(uid),
        "challenge_progress": user_challenges.get(uid, 0),
        "bonus_claimed": user_last_claim.get(uid) == datetime.date.today()
    })

@app.route('/bonus', methods=['POST'])
def bonus_endpoint():
    """Mini App daily bonus claim"""
    data = request.json or {}
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "No user_id"}), 400
    claim_bonus(int(user_id))
    return jsonify({"ok": True})

@app.route('/ad_complete', methods=['POST'])
def ad_complete():
    """Called when user finishes watching an Adsgram ad"""
    data = request.json or {}
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "No user_id"}), 400
    uid = int(user_id)
    pts = int(data.get("points", 10))
    add_points(uid, pts)
    user_ads[uid] = user_ads.get(uid, 0) + 1
    send_message(uid, f"📺 Ad watched! +{pts} points credited.")
    return jsonify({"ok": True, "balance": user_balances.get(uid, 0)})

@app.route('/withdraw', methods=['POST'])
def withdraw_endpoint():
    """Mini App withdrawal request"""
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    method  = data.get("method", "")
    account = data.get("account", "")
    amount  = int(data.get("amount", 0))

    if not user_id or amount < 500:
        return jsonify({"error": "Invalid request"}), 400

    current = user_balances.get(user_id, 0)
    if amount > current:
        return jsonify({"error": "Insufficient balance"}), 400

    user_balances[user_id] -= amount
    if user_id not in user_withdrawals:
        user_withdrawals[user_id] = []
    user_withdrawals[user_id].append({
        "method": method,
        "account": account,
        "amount": amount,
        "date": str(datetime.date.today()),
        "status": "pending"
    })

    send_message(user_id,
        f"✅ Withdrawal request received!\n"
        f"💳 Method: {method}\n"
        f"📧 Account: {account}\n"
        f"💰 Amount: {amount} points (≈ ${amount/100:.2f})\n\n"
        f"We'll process it within 24–48 hours."
    )
    return jsonify({"ok": True, "new_balance": user_balances[user_id]})

# ──────────────────────────────────────────────────────
#  CPX Survey Postback
# ──────────────────────────────────────────────────────
@app.route('/postback', methods=['GET'])
def postback():
    user_id    = request.args.get("user_id")
    amount_local = request.args.get("amount_local")
    amount_usd   = request.args.get("amount_usd")

    if user_id:
        uid = int(user_id)
        add_points(uid, int(float(amount_local)))
        user_surveys[uid] = user_surveys.get(uid, 0) + 1
        send_message(uid, f"✅ Survey confirmed! +{amount_local} points (≈${amount_usd})")

    return "OK"

# ──────────────────────────────────────────────────────
#  Helper Functions
# ──────────────────────────────────────────────────────
def send_message(chat_id, text):
    requests.post(f"{TELEGRAM_API}/sendMessage",
                  json={"chat_id": chat_id, "text": text})

def send_mini_app_button(chat_id):
    """Send a button that opens the Mini App"""
    requests.post(f"{TELEGRAM_API}/sendMessage", json={
        "chat_id": chat_id,
        "text": "🦉 Welcome to *WiseEarn*!\nEarn points by watching ads, completing surveys & daily tasks.",
        "parse_mode": "Markdown",
        "reply_markup": {
            "inline_keyboard": [[{
                "text": "🚀 Open WiseEarn App",
                "web_app": {"url": "https://YOUR_MINIAPP_URL"}  # 👈 Replace with your hosted URL
            }]]
        }
    })

def add_points(user_id, points):
    user_balances[user_id] = user_balances.get(user_id, 0) + points
    today = datetime.date.today()
    last = user_streaks.get(user_id)
    if last == today - datetime.timedelta(days=1):
        user_streaks[user_id] = today
    else:
        user_streaks[user_id] = today

def _get_streak(user_id):
    last = user_streaks.get(user_id)
    if not last:
        return 0
    today = datetime.date.today()
    if last == today or last == today - datetime.timedelta(days=1):
        return 1  # Simplified; use a counter for real streaks
    return 0

def claim_bonus(user_id):
    today = datetime.date.today()
    if user_last_claim.get(user_id) == today:
        send_message(user_id, "⚠️ You already claimed your bonus today.")
    else:
        add_points(user_id, 5)
        user_last_claim[user_id] = today
        user_challenges[user_id] = min(user_challenges.get(user_id, 0) + 1, 5)
        send_message(user_id, "🎁 Daily bonus claimed! +5 points.")

# ──────────────────────────────────────────────────────
@app.route('/referral_stats', methods=['GET'])
def referral_stats():
    """Get referral stats for Mini App"""
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"error": "No user_id"}), 400
    uid = int(user_id)
    refs = user_referrals.get(uid, [])
    earned = user_ref_earned.get(uid, 0)
    return jsonify({
        "referrals": len(refs),
        "ref_earned": earned,
        "ref_link": f"https://t.me/Wiseearn1bot?start=ref_{uid}"
    })

@app.route('/leaderboard', methods=['GET'])
def leaderboard():
    """Return top 10 users by balance"""
    mode = request.args.get("mode", "alltime")
    sorted_users = sorted(user_balances.items(), key=lambda x: x[1], reverse=True)[:10]
    board = []
    for uid, pts in sorted_users:
        board.append({"user_id": uid, "points": pts})
    return jsonify({"leaderboard": board, "mode": mode})

@app.route('/')
def home():
    return "🦉 WiseEarn backend running!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
