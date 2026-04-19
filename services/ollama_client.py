"""
Client per l'integrazione con Ollama
"""

import requests
import json
import subprocess
import re
from typing import List, Dict, Optional, Generator
from datetime import datetime


class OllamaClient:
    def __init__(self, base_url: str = "http://192.168.129.14:11434"):
        self.base_url = base_url.rstrip('/')
        
    def test_connection(self) -> bool:
        """Testa la connessione a Ollama"""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def list_models(self) -> List[Dict]:
        """Lista i modelli installati"""
        try:
            response = requests.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            return response.json().get('models', [])
        except Exception as e:
            print(f"Errore nel recupero modelli: {e}")
            return []
    
    def pull_model(self, model_name: str) -> Generator[Dict, None, None]:
        """Scarica un modello con progress tracking"""
        try:
            response = requests.post(
                f"{self.base_url}/api/pull",
                json={"name": model_name},
                stream=True
            )
            response.raise_for_status()
            
            for line in response.iter_lines():
                if line:
                    try:
                        data = json.loads(line.decode('utf-8'))
                        yield data
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            yield {"error": str(e)}
    
    def delete_model(self, model_name: str) -> bool:
        """Elimina un modello"""
        try:
            response = requests.delete(
                f"{self.base_url}/api/delete",
                json={"name": model_name}
            )
            return response.status_code == 200
        except:
            return False
    
    def generate_chat(self, model: str, messages: List[Dict], 
                     temperature: float = 0.7, max_tokens: int = 1000, timeout: int = 90) -> Dict:
        """Genera una risposta usando il modello"""
        try:
            payload = {
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens
                }
            }
            
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=timeout  # Usa timeout dinamico passato come parametro
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e)}
    
    def get_model_info(self, model_name: str) -> Optional[Dict]:
        """Ottiene informazioni su un modello specifico"""
        try:
            response = requests.post(
                f"{self.base_url}/api/show",
                json={"name": model_name}
            )
            response.raise_for_status()
            return response.json()
        except:
            return None
    
    def search_models(self, query: str = "") -> List[Dict]:
        """Cerca modelli disponibili (questa è una simulazione, Ollama non ha search)"""
        # Lista di modelli popolari per Ollama
        popular_models = [
            {"name": "llama3", "description": "Meta's Llama 3 model", "size": "4.7GB"},
            {"name": "llama3:70b", "description": "Meta's Llama 3 70B model", "size": "39GB"},
            {"name": "mistral", "description": "Mistral 7B model", "size": "4.1GB"},
            {"name": "gemma", "description": "Google's Gemma model", "size": "5.0GB"},
            {"name": "codellama", "description": "Code Llama model", "size": "3.8GB"},
            {"name": "phi", "description": "Microsoft's Phi model", "size": "1.6GB"},
            {"name": "neural-chat", "description": "Intel's Neural Chat model", "size": "4.1GB"},
            {"name": "starling-lm", "description": "Starling language model", "size": "4.1GB"},
            {"name": "orca-mini", "description": "Orca Mini model", "size": "1.9GB"},
            {"name": "vicuna", "description": "Vicuna model", "size": "4.1GB"},
            {"name": "wizard-vicuna", "description": "Wizard Vicuna model", "size": "4.1GB"},
            {"name": "nous-hermes", "description": "Nous Hermes model", "size": "4.1GB"},
            {"name": "dolphin-mixtral", "description": "Dolphin Mixtral model", "size": "26GB"},
            {"name": "qwen", "description": "Alibaba's Qwen model", "size": "4.1GB"},
            {"name": "deepseek-coder", "description": "DeepSeek Coder model", "size": "4.1GB"}
        ]
        
        if query:
            query = query.lower()
            return [m for m in popular_models if query in m["name"].lower() or query in m["description"].lower()]
        
        return popular_models


def parse_ollama_list_output(output: str) -> List[Dict]:
    """Parsifica l'output del comando 'ollama list'"""
    models = []
    lines = output.strip().split('\n')[1:]  # Salta l'header
    
    for line in lines:
        if line.strip():
            parts = line.split()
            if len(parts) >= 3:
                name = parts[0]
                tag = parts[1] if ':' in parts[0] else 'latest'
                if ':' not in name:
                    name = f"{name}:latest"
                
                # Cerca la dimensione (formato come "4.1 GB")
                size_str = ""
                for i, part in enumerate(parts):
                    if part.upper() in ['GB', 'MB', 'KB']:
                        size_str = f"{parts[i-1]} {part}"
                        break
                
                # Cerca la data di modifica
                modified = ""
                for i, part in enumerate(parts):
                    if re.match(r'\d{1,2}\s+(days?|weeks?|months?|hours?|minutes?)\s+ago', ' '.join(parts[i:i+3])):
                        modified = ' '.join(parts[i:i+3])
                        break
                
                models.append({
                    "name": name.split(':')[0],
                    "tag": name.split(':')[1] if ':' in name else 'latest',
                    "size": size_str,
                    "modified": modified
                })
    
    return models
