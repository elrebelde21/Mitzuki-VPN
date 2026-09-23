import subprocess
import logging
from typing import Dict

logger = logging.getLogger(__name__)

class DNSManager:
    """Verifica DNS usando comandos del sistema"""
    
    def verify_dns_records(self, domain: str, ip: str, tunnel_domain: str = None) -> Dict[str, bool]:
        """
        Verifica los registros A y NS
        domain = ds.mitzuki.xyz (servidor)
        tunnel_domain = d.mitzuki.xyz (túnel)
        """
        result = {
            'a_record': False,
            'ns_record': False,
            'a_record_value': None,
            'ns_record_value': None,
            'errors': []
        }
        
        # 1. Verificar registro A (ds.mitzuki.xyz → IP)
        try:
            cmd = ['dig', domain, 'A', '+short']
            output = subprocess.check_output(cmd, text=True).strip()
            
            if output:
                result['a_record'] = True
                result['a_record_value'] = output
                
                if output != ip:
                    result['errors'].append(f"⚠️ El registro A apunta a {output}, debería ser {ip}")
                    result['a_record'] = False
            else:
                result['errors'].append(f"❌ El dominio {domain} no tiene registro A")
        except Exception as e:
            result['errors'].append(f"❌ Error al verificar A: {str(e)}")
        
        # 2. Verificar registro NS (d.mitzuki.xyz → ds.mitzuki.xyz)
        if tunnel_domain:
            try:
                cmd = ['dig', tunnel_domain, 'NS', '+short']
                output = subprocess.check_output(cmd, text=True).strip()
                
                if output:
                    result['ns_record'] = True
                    result['ns_record_value'] = output
                    
                    if output != domain:
                        result['errors'].append(f"⚠️ El registro NS de {tunnel_domain} apunta a {output}, debería ser {domain}")
                        result['ns_record'] = False
                else:
                    result['errors'].append(f"❌ El dominio {tunnel_domain} no tiene registro NS")
            except Exception as e:
                result['errors'].append(f"❌ Error al verificar NS: {str(e)}")
        
        return result
    
    def get_dns_config_instructions(self, domain: str, ip: str, tunnel_domain: str = None) -> str:
        """
        Genera instrucciones para configurar DNS
        """
        if not tunnel_domain:
            tunnel_domain = f"d.{'.'.join(domain.split('.')[1:])}"
        
        # Extraer subdominios
        servidor_sub = domain.split('.')[0]  # ds
        tunel_sub = tunnel_domain.split('.')[0]  # d
        
        return f"""
📝 <b>INSTRUCCIONES DNS</b>

<b>1. Registro A (Servidor VayDNS)</b>
┌─────────────────────────────────────────────┐
│  Tipo: A                                    │
│  Nombre: {servidor_sub}                     │
│  Contenido: {ip}                           │
│  TTL: Auto                                  │
│  Proxy: 🔘 Desactivado                     │
└─────────────────────────────────────────────┘

<b>2. Registro NS (Dominio de Túnel)</b>
┌─────────────────────────────────────────────┐
│  Tipo: NS                                   │
│  Nombre: {tunel_sub}                        │
│  Contenido: {domain}                       │
│  TTL: Auto                                  │
│  Proxy: 🔘 Desactivado                     │
└─────────────────────────────────────────────┘

<b>🔍 Explicación:</b>
• {domain} → Es el servidor VayDNS
• {tunnel_domain} → Es el dominio que usan los clientes

<b>✅ Verificar:</b>
dig {domain} A
dig {tunnel_domain} NS
"""