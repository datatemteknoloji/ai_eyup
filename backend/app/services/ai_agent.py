"""
AI Agent Service - AI ile sunucu yönetimi ve komut çalıştırma
"""
import logging
import json
import re
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session
from app.models.server import Server
from app.services.ssh_manager import SSHManager
import httpx

logger = logging.getLogger(__name__)


class AIAgent:
    """AI destekli sunucu yönetim agent'ı"""
    
    def __init__(self, ollama_url: str = "http://192.168.1.166:11434"):
        self.ollama_url = ollama_url
        self.model = "llama3.1:8b"
    
    async def process_query(
        self, 
        user_query: str, 
        servers: List[Server],
        db: Session
    ) -> Dict:
        """
        Kullanıcı sorgusunu işle:
        1. Sorguyu analiz et
        2. Gerekirse SSH komutları oluştur
        3. Sunucularda çalıştır
        4. Sonuçları AI ile yorumla
        """
        
        # Adım 1: Sorguyu analiz et ve komut oluştur
        analysis = await self._analyze_query(user_query, servers)
        
        if not analysis.get("requires_command"):
            # Basit soru, direkt cevap ver
            return {
                "type": "answer",
                "response": analysis.get("response"),
                "commands_executed": []
            }
        
        # Adım 2: Komutları çalıştır
        command_results = []
        commands = analysis.get("commands", [])
        
        for cmd_info in commands:
            server_id = cmd_info.get("server_id")
            command = cmd_info.get("command")
            
            server = next((s for s in servers if s.id == server_id), None)
            if not server or not command:
                continue
            
            # SSH ile komutu çalıştır
            result = self._execute_command_on_server(server, command)
            command_results.append({
                "server": server.name,
                "ip": server.ip_address,
                "command": command,
                "success": result["success"],
                "output": result["output"],
                "error": result["error"]
            })
        
        # Adım 3: Sonuçları AI ile yorumla
        final_response = await self._summarize_results(
            user_query,
            command_results
        )
        
        return {
            "type": "command_execution",
            "response": final_response,
            "commands_executed": command_results
        }
    
    async def _analyze_query(self, query: str, servers: List[Server]) -> Dict:
        """Sorguyu analiz et ve hangi komutların çalıştırılacağını belirle"""
        
        server_info = "\n".join([
            f"- Server ID: {s.id}, Name: {s.name}, IP: {s.ip_address}, OS: {s.os_type}"
            for s in servers
        ])
        
        system_prompt = f"""Sen bir Linux sistem yöneticisi asistanısın. 
Kullanıcı senin yönettiğin sunucular hakkında soru soruyor.

Mevcut Sunucular:
{server_info}

Kullanıcı sorusu: {query}

Görevin:
1. Soruyu yanıtlamak için SSH komutu gerekiyorsa, hangi sunucularda hangi komutların çalıştırılması gerektiğini belirle.
2. Basit bir bilgi sorusuysa (açıklama, nasıl yapılır vb), direkt yanıtla.

JSON formatında yanıt ver:
{{
    "requires_command": true/false,
    "commands": [
        {{"server_id": 1, "command": "df -h"}},
        {{"server_id": 2, "command": "free -h"}}
    ],
    "response": "Açıklama veya basit yanıt"
}}
"""
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": system_prompt,
                        "stream": False,
                        "format": "json"
                    }
                )
                
                if response.status_code == 200:
                    result = response.json()
                    response_text = result.get("response", "{}")
                    
                    try:
                        return json.loads(response_text)
                    except:
                        # JSON parse hatası, basit yanıt döndür
                        return {
                            "requires_command": False,
                            "response": response_text
                        }
                else:
                    return {
                        "requires_command": False,
                        "response": "AI servisi şu anda kullanılamıyor."
                    }
                    
        except Exception as e:
            logger.error(f"AI query analysis failed: {e}")
            return {
                "requires_command": False,
                "response": f"Hata: {str(e)}"
            }
    
    def _execute_command_on_server(self, server: Server, command: str) -> Dict:
        """Sunucuda SSH komutu çalıştır"""
        try:
            config = server.connection_config or {}
            
            ssh = SSHManager(
                host=server.ip_address,
                username=config.get("username", "root"),
                password=config.get("password"),
                private_key=config.get("private_key"),
                port=config.get("port", 22),
                sudo_password=config.get("sudo_password")
            )
            
            if not ssh.connect():
                return {
                    "success": False,
                    "output": "",
                    "error": "SSH bağlantısı kurulamadı"
                }
            
            # Komutu çalıştır
            use_sudo = command.startswith("sudo ")
            success, stdout, stderr = ssh.execute_command(command, use_sudo=use_sudo)
            ssh.close()
            
            return {
                "success": success,
                "output": stdout.strip(),
                "error": stderr.strip() if stderr else ""
            }
            
        except Exception as e:
            logger.error(f"Command execution failed on {server.name}: {e}")
            return {
                "success": False,
                "output": "",
                "error": str(e)
            }
    
    async def _summarize_results(self, original_query: str, results: List[Dict]) -> str:
        """Komut sonuçlarını AI ile özetle"""
        
        results_text = "\n\n".join([
            f"Sunucu: {r['server']} ({r['ip']})\n"
            f"Komut: {r['command']}\n"
            f"Sonuç: {'Başarılı' if r['success'] else 'Başarısız'}\n"
            f"Çıktı:\n{r['output'][:500]}\n"
            f"{'Hata: ' + r['error'] if r['error'] else ''}"
            for r in results
        ])
        
        prompt = f"""Kullanıcı şunu sordu: "{original_query}"

Sunucularda çalıştırılan komutlar ve sonuçları:

{results_text}

Lütfen bu sonuçları özetleyerek kullanıcıya Türkçe, anlaşılır bir yanıt ver.
Önemli bilgileri vurgula, sorunları belirt, öneriler sun."""
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False
                    }
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return result.get("response", "Yanıt oluşturulamadı")
                else:
                    return f"AI yanıt hatası: {response.status_code}"
                    
        except Exception as e:
            logger.error(f"AI summarization failed: {e}")
            # Fallback: Ham sonuçları döndür
            summary = f"**{len(results)} sunucuda komut çalıştırıldı:**\n\n"
            for r in results:
                summary += f"**{r['server']}:** {r['command']}\n"
                if r['success']:
                    summary += f"```\n{r['output'][:200]}\n```\n\n"
                else:
                    summary += f"❌ Hata: {r['error']}\n\n"
            return summary
