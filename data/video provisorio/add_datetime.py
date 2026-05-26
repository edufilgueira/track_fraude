import cv2
from datetime import datetime, timedelta

INPUT_VIDEO = "cam.mp4"
OUTPUT_VIDEO = "output.mp4"

START_DATETIME = datetime(2026, 5, 22, 10, 0, 0)

cap = cv2.VideoCapture(INPUT_VIDEO)

fps = cap.get(cv2.CAP_PROP_FPS)

width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

fourcc = cv2.VideoWriter_fourcc(*'mp4v')

out = cv2.VideoWriter(
    OUTPUT_VIDEO,
    fourcc,
    fps,
    (width, height)
)

frame_id = 0

while True:
    ret, frame = cap.read()

    if not ret:
        break

    current_time = START_DATETIME + timedelta(seconds=frame_id / fps)

    text = current_time.strftime("%d/%m/%Y %H:%M:%S")

    cv2.rectangle(frame, (10, 10), (500, 60), (0, 0, 0), -1)

    cv2.putText(
        frame,
        text,
        (20, 45),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        (255, 255, 255),
        2,
        cv2.LINE_AA
    )

    out.write(frame)

    frame_id += 1

cap.release()
out.release()

print("Vídeo gerado:", OUTPUT_VIDEO)