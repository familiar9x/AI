PHẦN 1 Cài driver
---------------------------------------------------------------
sudo add-apt-repository ppa:graphics-drivers/ppa
sudo apt update
ubuntu-drivers devices


chọn bản cao nhất ví dụ:

sudo apt install nvidia-driver-570-open
sudo reboot

# verify GPU hoạt động
nvidia-smi


phải thấy GPU + VRAM


PHẦN 2 — Cài Ollama (LLM engine)
---------------------------------------------------------------
curl -fsSL https://ollama.com/install.sh | sh


run server

ollama serve


test:

curl http://localhost:11434


PHẦN 3 — Pull model để test
---------------------------------------------------------------
Model nhẹ test nhanh trước:

ollama pull llama3


test chat:

ollama run llama3


nếu GPU hoạt động đúng → load sẽ cực nhanh


PHẦN 4 — Pull model mạnh hơn để test GPU
---------------------------------------------------------------
RTX 5090 → chạy thoải mái model lớn

gợi ý:

ollama pull mistral-large


hoặc

ollama pull mixtral


PHẦN 5 — Cài Web UI chat (rất nên)
---------------------------------------------------------------
UI đẹp + multi user + API key + history

docker run -d \
  -p 3000:8080 \
  -v open-webui:/app/backend/data \
  ghcr.io/open-webui/open-webui:main


mở browser:

http://localhost:3000


login → chọn model → chat


PHẦN 6 — Test load GPU thật
---------------------------------------------------------------
mở terminal khác:

watch -n1 nvidia-smi


chat → thấy VRAM + compute tăng = OK


PHẦN 7 — Benchmark nhanh GPU mới
---------------------------------------------------------------
test tốc độ token:

ollama run llama3 "Write a 2000 word essay about AI"


quan sát:

Metric	tốt
load time	<3s
first token	<1s
tokens/sec	>80
PHẦN 8 — API call test (giống OpenAI format)
curl http://localhost:11434/api/generate \
  -d '{
    "model":"llama3",
    "prompt":"Hello"
  }'


→ bạn có thể dùng endpoint này cho app nội bộ

⚡ Tuning để GPU chạy max

file config:

~/.ollama/config


thêm:

OLLAMA_NUM_PARALLEL=4
OLLAMA_MAX_LOADED_MODELS=2

🧠 Model nên dùng với 5090 (khuyến nghị)
mục đích	model
chat	llama3 70b q4
coding	deepseek coder
reasoning	mixtral
RAG	mistral
