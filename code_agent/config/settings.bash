
LOCAL_URL="http://localhost:11434/v1/chat"
MODEL="gpt-oss:20b-cloud"
# Set environment variables for Ollama Cloud

export OLLAMA_CLOUD_KEY="$CLOUD_API_KEY"
export OLLAMA_CLOUD=1   # flag to force the script to hit the cloud
export OLLAMA_API_URL="$LOCAL_URL"
export OLLAMA_MODEL="$MODEL"
