import os
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    TemplateSendMessage, ButtonsTemplate, URITemplateAction, MessageTemplateAction,
    FollowEvent
)

app = Flask(__name__)

# LINE 金鑰
line_bot_api = LineBotApi(os.environ.get('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.environ.get('LINE_CHANNEL_SECRET'))

# Notion 金鑰與資料庫 ID[cite: 4]
NOTION_TOKEN = os.environ.get('NOTION_TOKEN')
DATABASE_ID = os.environ.get('DATABASE_ID')

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# 處理加入好友 (Follow) 事件
@handler.add(FollowEvent)
def handle_follow(event):
    user_id = event.source.user_id 
    
    query_url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    query_payload = {
        "filter": {
            "property": "UID",
            "title": {"equals": user_id}
        }
    }
    try:
        response = requests.post(query_url, headers=NOTION_HEADERS, json=query_payload)
        data = response.json()
        results = data.get("results", [])

        if len(results) == 0:
            create_url = "https://api.notion.com/v1/pages"
            create_payload = {
                "parent": {"database_id": DATABASE_ID},
                "properties": {
                    "UID": {"title": [{"text": {"content": user_id}}]},
                    "Token": {"number": 0}
                }
            }
            create_resp = requests.post(create_url, headers=NOTION_HEADERS, json=create_payload)
            if create_resp.status_code == 200:
                reply_message = TextSendMessage(text="🎉 歡迎加入！系統已自動為您建立闖關紀錄，請直接前往攤位掃碼開始闖關吧！")
            else:
                reply_message = TextSendMessage(text="⚠️ 系統建立紀錄失敗，請輸入「寫入我的 UID」手動建立。")
        else:
            reply_message = TextSendMessage(text="🎉 歡迎回來！您的闖關紀錄都還保留著，請繼續前往攤位挑戰吧！")

        line_bot_api.reply_message(event.reply_token, reply_message)
    except Exception as e:
        line_bot_api.reply_message(
            event.reply_token, 
            TextSendMessage(text=f"❌ 系統發生錯誤：\n{str(e)}")
        )

# 處理文字訊息事件
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    user_id = event.source.user_id 

    # 開發測試指令清單
    if user_message.lower() == "dev":
        reply_message = TextSendMessage(
            text="🛠️ 目前可用指令清單：\n"
                 "1. 寫入我的 UID (現在加好友已會自動寫入)\n"
                 "2. token (查詢目前點數)\n"
                 "3. reset (重設所有攤位與 Token 歸零)\n"
                 "4. 攤位A-正解 ~ 攤位I-正解 (進行對應攤位作答)\n"
        )
        line_bot_api.reply_message(event.reply_token, reply_message)

    # 1. 寫入 UID 指令 (由按鈕觸發或手動輸入)
    elif user_message == "寫入我的 UID":
        create_url = "https://api.notion.com/v1/pages"
        create_payload = {
            "parent": {"database_id": DATABASE_ID},
            "properties": {
                "UID": {"title": [{"text": {"content": user_id}}]},
                "Token": {"number": 0}
            }
        }
        try:
            response = requests.post(create_url, headers=NOTION_HEADERS, json=create_payload)
            data = response.json()
            if response.status_code == 200:
                reply_message = TextSendMessage(text=f"✅ 成功建立專屬檔案！\n初始 Token 為 0，馬上開始你的闖關吧！")
            else:
                reply_message = TextSendMessage(text=f"❌ 寫入失敗 (Status {response.status_code})：\n{data.get('message', response.text)}")
        except Exception as e:
            reply_message = TextSendMessage(text=f"❌ 程式發生例外錯誤：\n{str(e)}")

        line_bot_api.reply_message(event.reply_token, reply_message)

    # 2. 查詢目前點數指令：token
    elif user_message.lower() == "token":
        query_url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
        query_payload = {
            "filter": {
                "property": "UID",
                "title": {"equals": user_id}
            }
        }
        try:
            response = requests.post(query_url, headers=NOTION_HEADERS, json=query_payload)
            data = response.json()
            results = data.get("results", [])
            
            if len(results) > 0:
                props = results[0]["properties"]
                current_token = props.get("Token", {}).get("number", 0)
                reply_message = TextSendMessage(text=f"📊 目前擁有的點數 (Token)：{current_token} 點")
            else:
                # 找不到資料，跳出建立紀錄 Template
                not_found_template = ButtonsTemplate(
                    title='⚠️ 找不到闖關紀錄',
                    text='系統中尚未建立您的檔案，請點擊下方按鈕自動建立！',
                    actions=[
                        MessageTemplateAction(
                            label='建立闖關紀錄',
                            text='寫入我的 UID'
                        )
                    ]
                )
                reply_message = TemplateSendMessage(
                    alt_text='找不到闖關紀錄，請建立檔案',
                    template=not_found_template
                )
        except Exception as e:
            reply_message = TextSendMessage(text=f"❌ 查詢發生錯誤：\n{str(e)}")

        line_bot_api.reply_message(event.reply_token, reply_message)

    # 3. 重設指令：reset
    elif user_message.lower() == "reset":
        query_url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
        query_payload = {
            "filter": {
                "property": "UID",
                "title": {"equals": user_id}
            }
        }
        try:
            response = requests.post(query_url, headers=NOTION_HEADERS, json=query_payload)
            data = response.json()
            results = data.get("results", [])

            if len(results) == 0:
                not_found_template = ButtonsTemplate(
                    title='⚠️ 找不到闖關紀錄',
                    text='系統中尚未建立您的檔案，無法重設。請先建立紀錄！',
                    actions=[
                        MessageTemplateAction(
                            label='建立闖關紀錄',
                            text='寫入我的 UID'
                        )
                    ]
                )
                reply_message = TemplateSendMessage(
                    alt_text='找不到闖關紀錄，請建立檔案',
                    template=not_found_template
                )
            else:
                page_id = results[0]["id"]
                update_properties = {
                    "Token": {"number": 0}
                }
                for char in "ABCDEFGHI":
                    update_properties[f"攤位{char}"] = {"checkbox": False}

                update_url = f"https://api.notion.com/v1/pages/{page_id}"
                update_payload = {
                    "properties": update_properties
                }
                requests.patch(update_url, headers=NOTION_HEADERS, json=update_payload)
                reply_message = TextSendMessage(text=f"🔄 已成功重設！所有攤位狀態已清空資料，Token 已歸零。")
        except Exception as e:
            reply_message = TextSendMessage(text=f"❌ 重設發生錯誤：\n{str(e)}")

        line_bot_api.reply_message(event.reply_token, reply_message)


    # 5. 動態處理 攤位A-正解 至 攤位I-正解
    elif user_message.endswith("-正解") and user_message.startswith("攤位"):
        booth_name = user_message.replace("-正解", "").strip()
        valid_booths = [f"攤位{char}" for char in "ABCDEFGHI"]

        if booth_name not in valid_booths:
            reply_message = TextSendMessage(text=f"⚠️ 無此攤位代號！")
            line_bot_api.reply_message(event.reply_token, reply_message)
            return

        query_url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
        query_payload = {
            "filter": {
                "property": "UID",
                "title": {"equals": user_id}
            }
        }
        try:
            response = requests.post(query_url, headers=NOTION_HEADERS, json=query_payload)
            data = response.json()
            results = data.get("results", [])

            if len(results) == 0:
                # 找不到資料，跳出建立紀錄 Template
                not_found_template = ButtonsTemplate(
                    title='⚠️ 找不到闖關紀錄',
                    text='系統中尚未建立您的檔案，請點擊下方按鈕建立後再掃碼作答！',
                    actions=[
                        MessageTemplateAction(
                            label='建立闖關紀錄',
                            text='寫入我的 UID'
                        )
                    ]
                )
                reply_message = TemplateSendMessage(
                    alt_text='找不到闖關紀錄，請建立檔案',
                    template=not_found_template
                )
                line_bot_api.reply_message(event.reply_token, reply_message)
                return

            page_id = results[0]["id"]
            props = results[0]["properties"]
            
            is_checked = props.get(booth_name, {}).get("checkbox", False)
            current_token = props.get("Token", {}).get("number", 0)

            if is_checked:
                checked_template = ButtonsTemplate(
                    title=f'⚠️ {booth_name} 已經作答過了喔！',
                    text='請前往其他尚未挑戰的攤位繼續努力！',
                    actions=[
                        MessageTemplateAction(
                            label='繼續作答',
                            text='開始闖關~'
                        )
                    ]
                )
                reply_message = TemplateSendMessage(
                    alt_text=f'{booth_name} 已經作答過',
                    template=checked_template
                )
                line_bot_api.reply_message(event.reply_token, reply_message)
            else:
                new_token = current_token + 1
                
                if new_token >= 6:
                    final_token = 0
                    update_url = f"https://api.notion.com/v1/pages/{page_id}"
                    update_payload = {
                        "properties": {
                            booth_name: {"checkbox": True},
                            "Token": {"number": final_token}
                        }
                    }
                    requests.patch(update_url, headers=NOTION_HEADERS, json=update_payload)

                    buttons_template = ButtonsTemplate(
                        title='🎁 恭喜集滿 6 點！',
                        text='您已成功獲得兌換資格，請點擊下方按鈕出示或領取獎品！',
                        actions=[
                            URITemplateAction(
                                label='點擊領取您的禮物',
                                uri='https://lin.ee/TSoVKwj'
                            )
                        ]
                    )
                    reply_message = TemplateSendMessage(
                        alt_text='恭喜集滿 6 點！請查看您的禮物兌換券',
                        template=buttons_template
                    )
                    line_bot_api.reply_message(event.reply_token, reply_message)
                else:
                    update_url = f"https://api.notion.com/v1/pages/{page_id}"
                    update_payload = {
                        "properties": {
                            booth_name: {"checkbox": True},
                            "Token": {"number": new_token}
                        }
                    }
                    requests.patch(update_url, headers=NOTION_HEADERS, json=update_payload)
                    
                    continue_template = ButtonsTemplate(
                        title=f'🎉 {booth_name} 闖關成功！',
                        text=f'Token +1，目前共 {new_token} 點。還差 {6 - new_token} 點即可獲得禮物！',
                        actions=[
                            MessageTemplateAction(
                                label='繼續作答',
                                text='開始闖關~'
                            )
                        ]
                    )
                    template_message = TemplateSendMessage(
                        alt_text=f'{booth_name} 闖關成功',
                        template=continue_template
                    )
                    
                    line_bot_api.reply_message(event.reply_token, template_message)

        except Exception as e:
            reply_message = TextSendMessage(text=f"❌ 更新發生錯誤：\n{str(e)}")
            line_bot_api.reply_message(event.reply_token, reply_message)

    else:
        pass

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)