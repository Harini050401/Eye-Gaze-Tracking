import cv2
import mediapipe as mp
import pyautogui
import numpy as np
from collections import deque
import time
import math
import pyttsx3
import threading
import tkinter as tk

# ---------------- VOICE (FINAL FIX) ----------------
engine = pyttsx3.init()
engine.setProperty('rate', 140)
engine.setProperty('volume', 0.5)

# optional: force voice selection (helps on some systems)
voices = engine.getProperty('voices')
if voices:
    engine.setProperty('voice', voices[0].id)

def speak_text(text):
    def run():
        try:
            engine.stop()   # reset engine every time
            engine.say(text)
            engine.runAndWait()
        except:
            pass

    threading.Thread(target=run, daemon=True).start()

# ---------------- OVERLAY ----------------
root = tk.Tk()
root.overrideredirect(True)
root.attributes("-topmost", True)
root.attributes("-alpha", 0.85)

canvas = tk.Canvas(root, width=100, height=100, bg='black', highlightthickness=0)
canvas.pack()

overlay_visible = False

def show_overlay(x, y, progress):
    global overlay_visible

    size = 80
    root.geometry(f"{size}x{size}+{int(x)}+{int(y)}")

    canvas.delete("all")

    angle = int(progress * 360)

    canvas.create_arc(10, 10, size-10, size-10,
                      start=90, extent=-angle,
                      outline="cyan", width=4, style="arc")

    canvas.create_text(size//2, size//2,
                       text="Clicking...",
                       fill="white", font=("Arial", 9))

    if not overlay_visible:
        root.deiconify()
        overlay_visible = True

    root.update()

def hide_overlay():
    global overlay_visible
    if overlay_visible:
        root.withdraw()
        overlay_visible = False

threading.Thread(target=root.mainloop, daemon=True).start()
root.withdraw()

# ---------------- MEDIAPIPE ----------------
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(max_num_faces=1, refine_landmarks=True)

pyautogui.FAILSAFE = False
screen_w, screen_h = pyautogui.size()

LEFT_IRIS = [468, 469, 470, 471, 472]
RIGHT_IRIS = [473, 474, 475, 476, 477]
LEFT_EYE = [33, 133]
RIGHT_EYE = [362, 263]

positions_x = deque(maxlen=20)
positions_y = deque(maxlen=20)

calibrated = False
center_left = (0, 0)
center_right = (0, 0)

DEADZONE = 0.02
SENSITIVITY_X = 0.6
SENSITIVITY_Y = 0.8

prev_x, prev_y = screen_w / 2, screen_h / 2
MAX_STEP = 40
MARGIN = 20

LOCK_THRESHOLD = 10
UNLOCK_THRESHOLD = 25

cursor_locked = False
locked_x, locked_y = 0, 0

hover_start_time = None
click_delay = 4
warning_time = 2.5
voice_played = False

cap = cv2.VideoCapture(0)
cap.set(3, 1280)
cap.set(4, 720)

def lm_to_xy(lm, w, h):
    return int(lm.x * w), int(lm.y * h)

def avg_point(points):
    return np.mean(points, axis=0).astype(int)

def eye_ratio(iris, center, corners):
    left_x = min(c[0] for c in corners)
    right_x = max(c[0] for c in corners)
    top_y = min(c[1] for c in corners)
    bottom_y = max(c[1] for c in corners)

    ratio_x = (iris[0] - center[0]) / (right_x - left_x + 1e-6)
    ratio_y = (iris[1] - center[1]) / (bottom_y - top_y + 1e-6)

    return ratio_x, ratio_y

while True:
    ret, frame = cap.read()
    if not ret:
        break

    frame = cv2.flip(frame, 1)
    h, w, _ = frame.shape

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = face_mesh.process(rgb)

    if results.multi_face_landmarks:
        face = results.multi_face_landmarks[0]

        left_iris = [lm_to_xy(face.landmark[i], w, h) for i in LEFT_IRIS]
        right_iris = [lm_to_xy(face.landmark[i], w, h) for i in RIGHT_IRIS]

        left_center = avg_point(left_iris)
        right_center = avg_point(right_iris)

        left_eye = [lm_to_xy(face.landmark[i], w, h) for i in LEFT_EYE]
        right_eye = [lm_to_xy(face.landmark[i], w, h) for i in RIGHT_EYE]

        if not calibrated:
            center_left = left_center
            center_right = right_center
            calibrated = True
            print("Calibrated!")
            time.sleep(1)
            continue

        lx, ly = eye_ratio(left_center, center_left, left_eye)
        rx, ry = eye_ratio(right_center, center_right, right_eye)

        gx = (lx + rx) / 2
        gy = (ly + ry) / 2

        if abs(gx) < DEADZONE:
            gx = 0
        if abs(gy) < DEADZONE:
            gy = 0

        x = screen_w / 2 + gx * screen_w * SENSITIVITY_X
        y = screen_h / 2 + gy * screen_h * SENSITIVITY_Y

        x = np.clip(x, MARGIN, screen_w - MARGIN)
        y = np.clip(y, MARGIN, screen_h - MARGIN)

        positions_x.append(x)
        positions_y.append(y)

        smooth_x = np.mean(positions_x)
        smooth_y = np.mean(positions_y)

        dx = np.clip(smooth_x - prev_x, -MAX_STEP, MAX_STEP)
        dy = np.clip(smooth_y - prev_y, -MAX_STEP, MAX_STEP)

        new_x = prev_x + dx
        new_y = prev_y + dy

        pyautogui.moveTo(new_x, new_y, duration=0.1)

        movement = math.hypot(new_x - prev_x, new_y - prev_y)

        if not cursor_locked:
            if movement < LOCK_THRESHOLD:
                cursor_locked = True
                locked_x, locked_y = new_x, new_y
                hover_start_time = time.time()
                voice_played = False
        else:
            if movement > UNLOCK_THRESHOLD:
                cursor_locked = False
                hover_start_time = None
                voice_played = False
                hide_overlay()
            else:
                new_x, new_y = locked_x, locked_y

        # ---------------- FINAL CLICK SYSTEM ----------------
        if cursor_locked:

            elapsed = time.time() - hover_start_time

            if elapsed >= warning_time and not voice_played:
                speak_text("Ready to click")
                voice_played = True

            if warning_time <= elapsed < click_delay:
                progress = (elapsed - warning_time) / (click_delay - warning_time)
                show_overlay(new_x, new_y, progress)

            if elapsed >= click_delay:
                pyautogui.click()
                print("Clicked!")

                cursor_locked = False
                hover_start_time = None
                voice_played = False
                hide_overlay()

        prev_x, prev_y = new_x, new_y

        cv2.circle(frame, tuple(left_center), 3, (0, 255, 0), -1)
        cv2.circle(frame, tuple(right_center), 3, (0, 255, 0), -1)

    cv2.putText(frame, "Press 'q' to quit", (30, 50),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

    cv2.imshow("Eye Mouse + Smart Click", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()