"""
Servizio per l'annotazione automatica tramite AI
"""

import json
import re
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from sqlalchemy.orm import joinedload

from models import (
    db, User, Label, TextCell, CellAnnotation, 
    AIConfiguration, OpenRouterModel, OllamaModel
)
from services.ollama_client import OllamaClient
from services.openrouter_client import OpenRouterClient


class AIAnnotatorService:
    def __init__(self):
        self.ollama_client = None
        self.openrouter_client = None
        self.ai_user = None
        self.prompt_templates = self._load_prompt_templates()

    def _load_prompt_templates(self) -> Dict[int, Dict]:
        """
        Carica i template di prompt disponibili. In futuro può essere esteso per caricare da DB.
        Ogni template ha: 'name', 'description', 'template_text'.
        """
        return {
            1: {
                'name': 'Standard Quesiti',
                'description': 'Template ottimizzato per etichettare quesiti educativi e valutazioni',
                'template_text': (
                    "Etichetta questi testi educativi scegliendo dalle etichette fornite.\n\n"
                    "REGOLE:\n"
                    "- Usa SOLO etichette dalla lista (nomi esatti)\n"
                    "- Massimo 2 etichette per testo\n"
                    "- Se non appropriato, usa: \"\"\n\n"
                    "FORMATO JSON RICHIESTO:\n"
                    "[{\"index\": 0, \"label\": \"NomeEsatto\", \"confidence\": 0.9}]\n"
                )
            },
            2: {
                'name': 'Analisi Commenti',
                'description': 'Template focalizzato sull\'analisi dei commenti e feedback sui quesiti',
                'template_text': (
                    "Sei un assistente AI specializzato nell'analisi dei commenti e feedback relativi ai quesiti educativi.\n\n"
                    "Il tuo compito è categorizzare commenti, osservazioni e feedback per facilitare l'analisi qualitativa.\n\n"
                    "ISTRUZIONI SPECIFICHE:\n"
                    "1. Analizza il tono, il contenuto e l'intento di ogni commento\n"
                    "2. Identifica se il commento riguarda difficoltà, chiarezza, argomenti specifici, o aspetti metodologici\n"
                    "3. Assegna SOLO etichette dalla lista fornita (usa i nomi ESATTI)\n"
                    "4. Puoi assegnare multiple etichette se il commento tocca più aspetti\n"
                    "5. Se il commento non è rilevante o non è categorizzabile, usa etichetta vuota: \"\"\n"
                    "6. Considera sia il contenuto manifesto che quello latente del feedback\n\n"
                    "FORMATO RISPOSTA:\n"
                    "Rispondi SOLO in formato JSON valido come nell'esempio.\n"
                )
            },
            3: {
                'name': 'Analisi Competenze',
                'description': 'Template per identificare competenze e abilità richieste dai quesiti',
                'template_text': (
                    "Sei un assistente esperto nell'analisi pedagogica per identificare competenze e abilità.\n\n"
                    "Il tuo compito è analizzare quesiti per identificare le competenze cognitive e disciplinari richieste.\n\n"
                    "ISTRUZIONI SPECIFICHE:\n"
                    "1. Identifica il tipo di processo cognitivo richiesto (memoria, comprensione, applicazione, analisi, sintesi, valutazione)\n"
                    "2. Riconosci l'area disciplinare e il livello di complessità\n"
                    "3. Considera le competenze trasversali implicate (problem solving, comunicazione, pensiero critico)\n"
                    "4. Assegna SOLO etichette dalla lista fornita (usa i nomi ESATTI)\n"
                    "5. Privilegia etichette che descrivono competenze specifiche rispetto a quelle generiche\n"
                    "6. Se non identifichi competenze chiare, usa etichetta vuota: \"\"\n\n"
                    "FORMATO RISPOSTA:\n"
                    "Rispondi SOLO in formato JSON valido come specificato.\n"
                )
            }
        }

    def get_available_templates(self) -> Dict[int, Dict]:
        """Restituisce i template disponibili dal database con metadati"""
        from models import AIPromptTemplate
        
        try:
            templates = AIPromptTemplate.query.filter_by(is_active=True).all()
            
            result = {}
            for template in templates:
                result[template.id] = {
                    'name': template.name,
                    'description': template.description or f'Template per {template.category or "analisi generale"}',
                    'category': template.category
                }
            
            # Fallback ai template hardcoded se il database è vuoto
            if not result:
                return {
                    tid: {
                        'name': template['name'],
                        'description': template['description'],
                        'category': template.get('category', 'General')
                    }
                    for tid, template in self.prompt_templates.items()
                }
            
            return result
            
        except Exception as e:
            # Fallback ai template hardcoded in caso di errore
            print(f"Errore caricamento template dal DB: {e}")
            return {
                tid: {
                    'name': template['name'],
                    'description': template['description'],
                    'category': template.get('category', 'General')
                }
                for tid, template in self.prompt_templates.items()
            }

    def get_prompt_template(self, template_id: int = None) -> str:
        """Restituisce il testo del template selezionato dal database, o quello standard se non specificato."""
        from models import AIPromptTemplate
        
        try:
            if template_id:
                template = AIPromptTemplate.query.filter_by(id=template_id, is_active=True).first()
                if template:
                    return template.base_prompt
            
            # Fallback: prendi il primo template attivo
            first_template = AIPromptTemplate.query.filter_by(is_active=True).first()
            if first_template:
                return first_template.base_prompt
                
        except Exception as e:
            print(f"Errore caricamento template dal DB: {e}")
        
        # Ultimo fallback ai template hardcoded
        if template_id and template_id in self.prompt_templates:
            return self.prompt_templates[template_id]['template_text']
        return self.prompt_templates[1]['template_text']

    def build_annotation_prompt(self, texts: List[str], labels: List[Label], template_id: int = None) -> str:
        """
        Costruisce il prompt per l'annotazione AI usando un template e le etichette correnti del sistema
        Args:
            texts: Lista dei testi da annotare
            labels: Lista delle etichette correnti del sistema (sempre aggiornate)
            template_id: ID del template da usare
        """
        from collections import defaultdict
        
        # Organizza le etichette per categoria per una presentazione più chiara
        categories_dict = defaultdict(list)
        for label in labels:
            if not label.is_active or label.merged_into_label_id is not None:
                continue
            if label.category_obj and (not label.category_obj.is_active or label.category_obj.merged_into_category_id is not None):
                continue
            category_name = label.category_obj.name if label.category_obj else 'Generale'
            categories_dict[category_name].append(label)

        # Costruisce la lista delle categorie ed etichette in modo più strutturato
        categories_text = "ETICHETTE DISPONIBILI (sempre aggiornate dal sistema):\n"
        
        # Ordina le categorie per nome per consistenza
        for category in sorted(categories_dict.keys()):
            cat_labels = categories_dict[category]
            categories_text += f"\n=== {category} ===\n"
            
            # Ordina le etichette per nome all'interno della categoria
            for label in sorted(cat_labels, key=lambda x: x.name):
                # Aggiunge descrizione se disponibile e numero di utilizzi per contesto
                desc_part = f" - {label.description}" if label.description else ""
                usage_count = len(label.annotations) if hasattr(label, 'annotations') else 0
                usage_info = f" (usata {usage_count} volte)" if usage_count > 0 else " (mai usata)"
                categories_text += f"• {label.name}{desc_part}{usage_info}\n"

        # Parte generale dal template selezionato
        prompt = self.get_prompt_template(template_id)
        prompt += f"\n\n{categories_text}\n\n"
        
        # Aggiunge informazioni di contesto sui testi
        prompt += f"TESTI DA ETICHETTARE ({len(texts)} elementi):\n"
        prompt += "Ogni testo è numerato progressivamente. Analizza attentamente ciascuno:\n\n"

        # Aggiunge i testi con numerazione e pulizia migliorata
        for i, text in enumerate(texts):
            # Pulisce il testo mantenendo la leggibilità
            clean_text = re.sub(r'\s+', ' ', text.strip())
            # Tronca se troppo lungo ma mantiene il contesto
            if len(clean_text) > 800:
                clean_text = clean_text[:800] + "... [TRONCATO]"
            
            prompt += f"[{i}] {clean_text}\n\n"

        # Istruzioni finali più precise
        prompt += (
            "\nRispondi ESCLUSIVAMENTE con un JSON array valido.\n"
            "Ogni elemento deve avere: index (numero), label (nome esatto dalla lista), confidence (0.1-1.0).\n"
            "Non aggiungere testo prima o dopo il JSON.\n"
            "Esempio formato: [{\"index\": 0, \"label\": \"NomeEsattoDallaLista\", \"confidence\": 0.95}]"
        )
        
        return prompt

    def get_or_create_ai_user(self) -> User:
        """Ottiene o crea l'utente AI"""
        if not self.ai_user:
            self.ai_user = User.query.filter_by(username='ai_assistant').first()
            if not self.ai_user:
                self.ai_user = User(
                    username='ai_assistant',
                    email='ai@system.local',
                    role='annotatore'
                )
                self.ai_user.set_password('N/A')
                db.session.add(self.ai_user)
                db.session.commit()
        return self.ai_user
    
    def get_active_configuration(self) -> Optional[AIConfiguration]:
        """Ottiene la configurazione AI attiva"""
        return AIConfiguration.query.filter_by(is_active=True).first()
    
    def initialize_clients(self, config: AIConfiguration = None):
        """Inizializza i client AI"""
        if not config:
            config = self.get_active_configuration()
        
        if not config:
            raise ValueError("Nessuna configurazione AI attiva trovata")
        
        if config.provider == 'ollama':
            self.ollama_client = OllamaClient(config.ollama_url)
        elif config.provider == 'openrouter':
            self.openrouter_client = OpenRouterClient(config.openrouter_api_key)
    
    def generate_annotations(
        self,
        file_id: int,
        batch_size: int = 3,
        mode: str = 'new',
        template_id: int = None,
        selected_categories: List[str] = None,
        max_tokens: int = 500,
        timeout: int = 90,
        question_name: Optional[str] = None,
        max_cells_per_session: int = 20
    ) -> Dict:
        """
        Genera annotazioni AI per un file
        
        Args:
            file_id: ID del file Excel
            batch_size: Numero di testi per batch (ridotto per evitare timeout)
            mode: Modalità di etichettatura ('new', 'additional', 'replace')
            template_id: ID del template prompt da usare
            selected_categories: Lista delle categorie selezionate per il prompt
            max_tokens: Numero massimo di token per risposta AI
            timeout: Timeout in secondi per le chiamate AI
            question_name: Se valorizzato limita la generazione a una specifica domanda/colonna
            max_cells_per_session: Limite massimo di celle processate in una singola richiesta
        """
        try:
            # Ottiene la configurazione attiva
            config = self.get_active_configuration()
            if not config:
                return {"error": "Nessuna configurazione AI attiva"}

            self.initialize_clients(config)

            # Ottiene le etichette disponibili con join per evitare problemi di lazy loading
            if selected_categories:
                from models import Category
                categories = Category.query.filter(
                    Category.name.in_(selected_categories),
                    Category.is_active == True,  # noqa: E712
                    Category.merged_into_category_id.is_(None)
                ).all()
                labels = []
                for cat in categories:
                    labels.extend(
                        Label.query.options(db.joinedload(Label.category_obj)).filter(
                            Label.category_id == cat.id,
                            Label.is_active == True,  # noqa: E712
                            Label.merged_into_label_id.is_(None)
                        ).all()
                    )
            else:
                labels = Label.query.options(db.joinedload(Label.category_obj)).filter(
                    Label.is_active == True,  # noqa: E712
                    Label.merged_into_label_id.is_(None)
                ).order_by(Label.name).all()
                labels = [
                    lbl for lbl in labels
                    if not lbl.category_obj or (
                        lbl.category_obj.is_active and lbl.category_obj.merged_into_category_id is None
                    )
                ]
            
            if not labels:
                return {"error": "Nessuna etichetta attiva disponibile"}

            # Filtro base: file e, opzionalmente, domanda specifica
            base_filters = [TextCell.excel_file_id == file_id]
            if question_name:
                base_filters.append(TextCell.column_name == question_name)

            # Ottiene i testi da annotare in base alla modalità
            if mode == 'replace':
                # Ri-etichettatura: tutte le celle
                target_cells = TextCell.query.filter(*base_filters).all()
                print(f"🔄 Modalità sostituzione: {len(target_cells)} celle totali")
            elif mode == 'additional':
                # Etichettatura aggiuntiva: tutte le celle (anche quelle già annotate)
                target_cells = TextCell.query.filter(*base_filters).all()
                print(f"➕ Modalità aggiuntiva: {len(target_cells)} celle totali")
            else:  # mode == 'new'
                # Modalità normale: solo celle non annotate
                target_cells = TextCell.query.filter(
                    *base_filters,
                    ~TextCell.id.in_(
                        db.session.query(CellAnnotation.text_cell_id).distinct()
                    )
                ).all()
                print(f"🆕 Modalità nuove: {len(target_cells)} celle non annotate")

            if not target_cells:
                message = f"Nessuna cella da elaborare per modalità '{mode}'"
                return {"message": message, "annotations": []}

            # Processa in batch più piccoli per evitare timeout
            all_annotations = []
            total_processed = 0
            max_cells_per_session = int(max_cells_per_session) if max_cells_per_session else 20
            if max_cells_per_session <= 0:
                max_cells_per_session = 20

            # Limita il numero di celle da processare
            cells_to_process = target_cells[:max_cells_per_session]

            for i in range(0, len(cells_to_process), batch_size):
                batch_cells = cells_to_process[i:i + batch_size]
                batch_texts = [cell.text_content for cell in batch_cells]

                batch_num = i//batch_size + 1
                total_batches = (len(cells_to_process) + batch_size - 1) // batch_size
                print(f"📝 Processando batch {batch_num}/{total_batches}: {len(batch_cells)} celle")

                # Genera le annotazioni per questo batch
                batch_annotations = self._process_batch(
                    batch_texts, batch_cells, labels, config, mode, template_id, max_tokens, timeout
                )

                print(f"✅ Batch {batch_num}: {len(batch_annotations)} annotazioni generate")
                all_annotations.extend(batch_annotations)
                total_processed += len(batch_cells)

                # Pausa tra i batch per evitare overload
                import time
                time.sleep(2)  # Aumentato da 1 a 2 secondi

            return {
                "message": f"Generate {len(all_annotations)} annotazioni (modalità: {mode})",
                "annotations": all_annotations,
                "total_processed": total_processed,
                "mode": mode,
                "question_name": question_name,
                "remaining_cells": max(0, len(target_cells) - len(cells_to_process)),
                "total_target_cells": len(target_cells),
                "max_cells_per_session": max_cells_per_session
            }

        except Exception as e:
            print(f"❌ Errore in generate_annotations: {e}")
            return {"error": str(e)}
    
    def _process_batch(self, texts: List[str], cells: List[TextCell], 
                      labels: List[Label], config: AIConfiguration, mode: str = 'new', 
                      template_id: int = None, max_tokens: int = 500, timeout: int = 90) -> List[Dict]:
        """
        Processa un batch di testi
        
        Args:
            texts: Lista dei testi da annotare
            cells: Lista delle celle corrispondenti
            labels: Lista delle etichette disponibili (filtrate per categorie)
            config: Configurazione AI
            mode: Modalità di etichettatura ('new', 'additional', 'replace')
            template_id: ID del template prompt da usare
            max_tokens: Numero massimo di token per risposta
            timeout: Timeout in secondi per chiamata AI
        """
        annotations = []
        
        try:
            # Costruisce il prompt con il template selezionato e le etichette aggiornate
            prompt = self.build_annotation_prompt(texts, labels, template_id)
            
            # Prepara i messaggi
            messages = [
                {"role": "system", "content": config.system_prompt or "Sei un assistente per l'etichettatura di testi."},
                {"role": "user", "content": prompt}
            ]
            
            # Chiama l'AI con retry logic
            response = None
            max_retries = 2
            retry_count = 0
            
            while retry_count <= max_retries:
                try:
                    if config.provider == 'ollama':
                        response = self.ollama_client.generate_chat(
                            config.ollama_model,
                            messages,
                            config.temperature,
                            max_tokens,  # Usa parametro dinamico
                            timeout      # Usa parametro dinamico
                        )
                    elif config.provider == 'openrouter':
                        response = self.openrouter_client.generate_chat(
                            config.openrouter_model,
                            messages,
                            config.temperature,
                            max_tokens   # Usa parametro dinamico
                        )
                    
                    # Se la risposta è valida, esce dal loop
                    if response and 'error' not in response:
                        break
                        
                except Exception as e:
                    print(f"⚠️ Tentativo {retry_count + 1} fallito: {e}")
                    
                retry_count += 1
                if retry_count <= max_retries:
                    print(f"🔄 Nuovo tentativo in 3 secondi... ({retry_count}/{max_retries})")
                    import time
                    time.sleep(3)
            
            if not response or 'error' in response:
                print(f"Errore nella risposta AI: {response}")
                return annotations
            
            # Estrae il contenuto della risposta
            content = ""
            if config.provider == 'ollama':
                content = response.get('message', {}).get('content', '')
            elif config.provider == 'openrouter':
                content = response.get('choices', [{}])[0].get('message', {}).get('content', '')
            
            # Parsifica le annotazioni
            ai_annotations = self._parse_ai_response(content)
            

            # Crea le annotazioni nel database
            ai_user = self.get_or_create_ai_user()
            label_map = {label.name.lower(): label for label in labels}
            re_annotate = mode == 'replace'

            for ai_ann in ai_annotations:
                if ai_ann['index'] < len(cells):
                    cell = cells[ai_ann['index']]
                    # Gestisce il caso in cui label può essere stringa o lista
                    label_raw = ai_ann.get('label', '')
                    if isinstance(label_raw, list):
                        # Se è una lista, prende il primo elemento
                        label_name = label_raw[0] if label_raw else ''
                    else:
                        label_name = str(label_raw)
                    
                    # Converte a lowercase per il match
                    label_name = label_name.lower() if label_name else ''
                    
                    # Salta se l'etichetta è vuota
                    if not label_name or label_name.strip() == "":
                        continue
                    
                    # Trova l'etichetta corrispondente (match esatto prima)
                    label = label_map.get(label_name)
                    if not label:
                        # Cerca match parziale solo se non trova match esatto
                        label_name_clean = label_name.strip()
                        for name, lbl in label_map.items():
                            if label_name_clean == name.lower() or label_name_clean in name.lower() or name.lower() in label_name_clean:
                                label = lbl
                                break

                    if label:
                        # Se è modalità ri-etichettatura, rimuovi le annotazioni esistenti dell'utente AI
                        if re_annotate:
                            existing_ai_annotations = CellAnnotation.query.filter_by(
                                text_cell_id=cell.id,
                                user_id=ai_user.id,
                                is_ai_generated=True
                            ).all()
                            for existing_ann in existing_ai_annotations:
                                db.session.delete(existing_ann)

                        # Crea la nuova annotazione con status pending_review
                        annotation = CellAnnotation(
                            text_cell_id=cell.id,
                            label_id=label.id,
                            user_id=ai_user.id,
                            is_ai_generated=True,
                            ai_confidence=ai_ann.get('confidence', 0.5),
                            ai_model=config.ollama_model or config.openrouter_model,
                            ai_provider=config.provider,
                            status='pending_review'
                        )

                        db.session.add(annotation)
                        annotations.append({
                            'text': cell.text_content[:100] + '...',
                            'label': label.name,
                            'confidence': ai_ann.get('confidence', 0.5)
                        })
            
            db.session.commit()
        
        except Exception as e:
            print(f"Errore nel processamento batch: {e}")
            db.session.rollback()
        
        return annotations
    
    def _parse_ai_response(self, content: str) -> List[Dict]:
        """
        Parsifica la risposta JSON dell'AI con gestione migliorata degli errori
        """
        if not content or content.strip() == "":
            print("Risposta AI vuota")
            return []
        
        try:
            # Pulisce la risposta da eventuali caratteri di controllo
            content = content.strip()
            
            # Prova prima a estrarre il JSON dalla risposta (può esserci testo aggiuntivo)
            json_patterns = [
                r'\[.*?\]',  # Array JSON standard
                r'\{.*?\}',  # Oggetto JSON singolo (lo convertiremo in array)
                r'```json\s*(\[.*?\])\s*```',  # JSON in code block
                r'```\s*(\[.*?\])\s*```',  # JSON in code block generico
            ]
            
            json_str = None
            for pattern in json_patterns:
                match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
                if match:
                    json_str = match.group(1) if len(match.groups()) > 0 else match.group(0)
                    break
            
            # Se non trova pattern specifici, prova l'intera risposta
            if not json_str:
                json_str = content
            
            # Parsifica il JSON
            parsed = json.loads(json_str)
            
            # Se è un oggetto singolo, lo converte in array
            if isinstance(parsed, dict):
                parsed = [parsed]
            elif not isinstance(parsed, list):
                print(f"Formato risposta AI non valido: {type(parsed)}")
                return []
            
            # Valida la struttura di ogni elemento
            validated_annotations = []
            for i, item in enumerate(parsed):
                if not isinstance(item, dict):
                    print(f"Elemento {i} non è un dizionario: {item}")
                    continue
                
                # Validazione campi obbligatori
                if 'index' not in item:
                    print(f"Elemento {i} manca il campo 'index': {item}")
                    continue
                
                if 'label' not in item:
                    print(f"Elemento {i} manca il campo 'label': {item}")
                    continue
                
                # Normalizza i valori
                try:
                    index = int(item['index'])
                    label = str(item['label']).strip()
                    confidence = float(item.get('confidence', 0.5))
                    
                    # Limita confidence tra 0.1 e 1.0
                    confidence = max(0.1, min(1.0, confidence))
                    
                    validated_annotations.append({
                        'index': index,
                        'label': label,
                        'confidence': confidence
                    })
                    
                except (ValueError, TypeError) as e:
                    print(f"Errore nella conversione dell'elemento {i}: {e}")
                    continue
            
            return validated_annotations
            
        except json.JSONDecodeError as e:
            print(f"Errore nel parsing JSON: {e}")
            print(f"Contenuto originale: {content[:500]}...")
            return []
        except Exception as e:
            print(f"Errore imprevisto nel parsing: {e}")
            return []
    
    def generate_response(self, prompt: str, config: 'AIConfiguration', timeout: int = 90) -> Dict:
        """
        Invia un prompt al provider AI configurato e restituisce la risposta testuale.
        Usato da BulkAnnotationService.
        """
        try:
            self.initialize_clients(config)
            messages = [
                {"role": "system", "content": config.system_prompt or "Sei un assistente per l'etichettatura di testi."},
                {"role": "user", "content": prompt}
            ]

            if config.provider == 'ollama':
                raw = self.ollama_client.generate_chat(
                    config.ollama_model, messages, config.temperature,
                    config.max_tokens or 1000, timeout
                )
            elif config.provider == 'openrouter':
                raw = self.openrouter_client.generate_chat(
                    config.openrouter_model, messages, config.temperature,
                    config.max_tokens or 1000
                )
            else:
                return {"success": False, "error": f"Provider non supportato: {config.provider}"}

            if not raw or 'error' in raw:
                return {"success": False, "error": raw.get('error', 'Risposta vuota') if raw else 'Nessuna risposta'}

            if config.provider == 'ollama':
                text = raw.get('message', {}).get('content', '')
            else:
                text = raw.get('choices', [{}])[0].get('message', {}).get('content', '')

            return {"success": True, "response": text}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def review_annotation(self, annotation_id: int, action: str, reviewer_id: int) -> bool:
        """Rivede un'annotazione AI (accetta/rifiuta)"""
        try:
            annotation = CellAnnotation.query.get(annotation_id)
            if not annotation or not annotation.is_ai_generated:
                return False
            
            if action == 'accept':
                annotation.status = 'active'
            elif action == 'reject':
                annotation.status = 'rejected'
            else:
                return False
            
            annotation.reviewed_by = reviewer_id
            annotation.reviewed_at = datetime.utcnow()
            
            db.session.commit()
            return True
            
        except Exception as e:
            print(f"Errore nella revisione: {e}")
            db.session.rollback()
            return False
    
    def get_pending_annotations(self, file_id: int = None) -> List[Dict]:
        """Ottiene le annotazioni in attesa di revisione"""
        query = CellAnnotation.query.filter(
            CellAnnotation.is_ai_generated == True,
            CellAnnotation.status == 'pending_review'
        )
        
        if file_id:
            query = query.join(TextCell).filter(TextCell.excel_file_id == file_id)
        
        annotations = query.all()
        
        result = []
        for ann in annotations:
            result.append({
                'id': ann.id,
                'text': ann.text_cell.text_content,
                'label': ann.label.name,
                'confidence': ann.ai_confidence,
                'model': ann.ai_model,
                'provider': ann.ai_provider,
                'created_at': ann.created_at.isoformat()
            })
        
        return result
