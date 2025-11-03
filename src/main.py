import os
import datetime
import threading
import tkinter as tk
from tkinter.scrolledtext import ScrolledText
import queue
import glob
from pythonosc.udp_client import SimpleUDPClient
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import time 

# --- 設定はじめ ---
LOG_DIR = os.path.join(
    os.environ.get('APPDATA', ''), '..', 'LocalLow', 'VRChat', 'VRChat'
)
OSC_IP = "127.0.0.1"
OSC_PORT = 9000
JOIN_ADDRESS = "/avatar/parameters/PmmaOSC/Notification1"
LEAVE_ADDRESS = "/avatar/parameters/PmmaOSC/Notification2"
NOTIFICATION_DURATION = 0.05

TIME_HOURS_ADDRESS = "/avatar/parameters/PmmaOSC/TimeHours"
TIME_MINUTES_ADDRESS = "/avatar/parameters/PmmaOSC/TimeMinutes"

JOIN_KEY = "[Behaviour] OnPlayerEnteredRoom"
LEAVE_KEY = "[Behaviour] OnPlayerLeftRoom"
# --- 設定おわり ---

# OSCクライアントの初期化
try:
    client = SimpleUDPClient(OSC_IP, OSC_PORT)
except Exception as e:
    print(f"OSCクライアントの初期化に失敗: {e}")
    client = None

# GUI通信キュー
log_queue = queue.Queue()

# --- ユーティリティ関数 ---
def find_latest_log_file(log_dir):
    if not os.path.isdir(log_dir):
        return None
    list_of_files = glob.glob(os.path.join(log_dir, 'output_log_*.txt'))
    try:
        return max(list_of_files, key=os.path.getmtime) if list_of_files else None
    except Exception:
        return None

def send_osc_notification_async(address, duration):
    """OSC通知を非同期で送信します（True -> False）。"""
    if not client: return

    client.send_message(address, True)
    
    def send_false():
        if client:
            client.send_message(address, False)

    t = threading.Timer(duration, send_false)
    t.daemon = True
    t.start()
    
# --- ログファイル監視 ---
class LogFileHandler(FileSystemEventHandler):
    def __init__(self, log_file_path, log_q):
        super().__init__()
        self.log_file_path = log_file_path
        try:
            self.last_read_position = os.path.getsize(log_file_path)
        except OSError:
            self.last_read_position = 0
            
        self.log_q = log_q

    def on_modified(self, event):
        if event.src_path == self.log_file_path:
            self.read_new_logs()

    def read_new_logs(self):
        try:
            with open(self.log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(self.last_read_position)
                new_lines = f.readlines()
                
                for line in new_lines:
                    line = line.strip()
                    if JOIN_KEY in line:
                        self.log_q.put("プレイヤーがJoinしました")
                        send_osc_notification_async(JOIN_ADDRESS, NOTIFICATION_DURATION)
                    elif LEAVE_KEY in line:
                        self.log_q.put("プレイヤーがLeaveしました")
                        send_osc_notification_async(LEAVE_ADDRESS, NOTIFICATION_DURATION)

                self.last_read_position = f.tell()

        except Exception as e:
            self.log_q.put(f"【エラー】ログファイルの読み込みまたは処理中にエラーが発生しました: {e}")

# --- GUI ---
class PmmaOSCSender(tk.Tk):
    
    def __init__(self, log_q, log_dir):
        super().__init__()
        self.title("PmmaOSCSender")
        self.geometry("400x300")
        self.log_q = log_q
        self.log_dir = log_dir
        self.current_log_path = None
        self.observer = None
        
        # 時刻表示
        self.clock_label = tk.Label(self, text="--:--", font=("Helvetica", 40, "bold"))
        self.clock_label.pack(pady=5) 

        # 情報表示
        self.info_label = tk.Label(self, text=f"OSC: {OSC_IP}:{OSC_PORT}", justify=tk.LEFT, font=("Helvetica", 10))
        self.info_label.pack(pady=(0, 5))

        # ログ表示
        self.log_text = ScrolledText(self, state='disabled', height=8, width=45, font=("Courier", 10))
        self.log_text.pack(pady=(0, 5), padx=5)
        
        # --- メソッドの開始 ---
        self.init_monitoring() 
        self.after(50, self.poll_queue)
        
        # 更新を予約
        self.perform_update() 

        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def update_info_label(self, log_path):
        """情報ラベルを更新します。"""
        log_file_name = log_path.split(os.sep)[-1] if log_path else 'ファイルなし'
        info_text = f"OSC: {OSC_IP}:{OSC_PORT}\n監視ログ: {log_file_name}"
        self.info_label.config(text=info_text)

    def init_monitoring(self):
        """プログラム起動時の初期監視を開始します。"""
        latest_log = find_latest_log_file(self.log_dir)
        
        if not latest_log:
            self.add_log("【エラー】最新のログファイルが見つかりません。")
            self.update_info_label(None)
            return
            
        # ログファイル監視開始
        self.start_log_monitoring(latest_log)

    def start_log_monitoring(self, log_file_path):
        """ログ監視を開始または切り替えします。"""
        
        # 既存の監視を停止
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=0.5) 
            self.observer = None 
            
        self.current_log_path = log_file_path
        self.update_info_label(self.current_log_path)
        self.add_log(f"ログ監視を開始: {log_file_path.split(os.sep)[-1]}")
        
        # 新しい監視を開始
        event_handler = LogFileHandler(log_file_path, self.log_q)
        self.observer = Observer()
        self.observer.schedule(event_handler, self.log_dir, recursive=False)
        self.observer.start()

    def check_for_new_log_file(self):
        """最新のログファイルを確認し、必要であれば監視対象を切り替えます。"""
        
        new_latest_log = find_latest_log_file(self.log_dir)
        
        if not new_latest_log:
             if not self.current_log_path:
                 self.add_log("【エラー】最新のログファイルが見つかりません。")
             return

        if new_latest_log != self.current_log_path:
            self.add_log(f"新しいログファイル検出。監視対象を切り替えます。")
            self.start_log_monitoring(new_latest_log)

    def schedule_next_update(self):
        now = datetime.datetime.now()
        next_minute = now.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)
        
        wait_time_ms = int((next_minute - now).total_seconds() * 1000)
        
        wait_time_ms = max(50, wait_time_ms) 
        
        self.after(wait_time_ms, self.perform_update)
        
    def perform_update(self):
        
        # ログファイルチェック
        self.check_for_new_log_file() 
        
        # 時計更新
        current_time_str = datetime.datetime.now().strftime('%H:%M')
        self.clock_label.config(text=current_time_str)
        
        # OSC時刻送信
        self.send_current_time_osc() 
        
        # 更新予約
        self.schedule_next_update()


    def send_current_time_osc(self):
        if client:
            now = datetime.datetime.now()
            hour = now.hour
            minute = now.minute
            
            client.send_message(TIME_HOURS_ADDRESS, hour)
            client.send_message(TIME_MINUTES_ADDRESS, minute)

    
    def poll_queue(self):
        try:
            while not self.log_q.empty():
                message = self.log_q.get_nowait()
                self.add_log(message)
        except queue.Empty:
            pass 
        
        self.after(50, self.poll_queue) 

    def add_log(self, message):
        timestamp = datetime.datetime.now().strftime('[%H:%M:%S] ')
        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, timestamp + message + '\n')
        self.log_text.see(tk.END) 
        self.log_text.config(state='disabled')

    def on_closing(self):
        
        # Observer停止
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=1.0) 
            
        global client
        client = None 

        self.destroy() 

# --- メイン実行 ---
if __name__ == "__main__":
    app = PmmaOSCSender(
        log_q=log_queue, 
        log_dir=LOG_DIR
    )
    app.mainloop()
    