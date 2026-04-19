"""
Servizio per l'annotazione batch di celle con template di prompt
"""

import json
import re
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime

from models import db, TextCell, CellAnnotation, PromptTemplate, AIConfiguration, Label
from services.ai_annotator import AIAnnotatorService

class BulkAnnotationService:
    """Servizio per l'annotazione batch di celle usando template di prompt"""
    
    def __init__(self):
        self.ai_service = AIAnnotatorService()
    
    def get_cells_by_criteria(self, file_id: int, question: str, options: Dict[str, Any]) -> List[TextCell]:
        """
        Recupera le celle secondo i criteri specificati
        
        Args:
            file_id: ID del file Excel
            question: Nome del quesito
            options: Dizionario con opzioni di filtro
                - filter_valid_cells: bool - filtra celle valide (>=4 caratteri, non vuote)
                - annotation_state: str - 'unannotated', 'annotated', 'reannotate', 'all'
                - min_chars: int - numero minimo di caratteri
        
        Returns:
            Lista di TextCell che soddisfano i criteri
        """
        # Query base per le celle del quesito
        query = TextCell.query.filter_by(
            excel_file_id=file_id,
            column_name=question
        )
        
        # Filtra celle valide se richiesto
        if options.get('filter_valid_cells', True):
            min_chars = options.get('min_chars', 4)
            query = query.filter(
                TextCell.text_content.isnot(None),
                db.func.length(TextCell.text_content) >= min_chars
            )
        
        # Filtra per stato di annotazione
        annotation_state = options.get('annotation_state', 'unannotated')
        
        if annotation_state == 'unannotated':
            # Solo celle senza annotazioni attive
            query = query.filter(
                ~TextCell.id.in_(
                    db.session.query(CellAnnotation.text_cell_id)
                    .filter_by(status='active')
                    .subquery()
                )
            )
        elif annotation_state == 'annotated':
            # Solo celle con annotazioni attive
            query = query.filter(
                TextCell.id.in_(
                    db.session.query(CellAnnotation.text_cell_id)
                    .filter_by(status='active')
                    .subquery()
                )
            )
        elif annotation_state == 'reannotate':
            # Solo celle con annotazioni da ri-etichettare (quelle AI in pending)
            query = query.filter(
                TextCell.id.in_(
                    db.session.query(CellAnnotation.text_cell_id)
                    .filter_by(status='pending_review', is_ai_generated=True)
                    .subquery()
                )
            )
        # annotation_state == 'all' non aggiunge filtri
        
        return query.order_by(TextCell.id).all()
    
    def format_content_for_prompt(self, cells: List[TextCell]) -> str:
        """
        Formatta il contenuto delle celle per il prompt
        
        Args:
            cells: Lista di celle da formattare
        
        Returns:
            Stringa formattata per il prompt
        """
        content_lines = []
        
        for i, cell in enumerate(cells, 1):
            # Limita la lunghezza del testo per il prompt
            text = cell.text_content[:500] if len(cell.text_content) > 500 else cell.text_content
            content_lines.append(f"Risposta {i} (ID: {cell.id}): {text}")
        
        return "\n".join(content_lines)
    
    def preview_annotation_job(self, file_id: int, question: str, template_id: int, 
                             config_id: int, options: Dict[str, Any]) -> Dict[str, Any]:
        """
        Genera un'anteprima del job di annotazione
        
        Returns:
            Dizionario con informazioni di anteprima
        """
        # Recupera i dati necessari
        cells = self.get_cells_by_criteria(file_id, question, options)
        template = PromptTemplate.query.get(template_id)
        config = AIConfiguration.query.get(config_id)
        
        if not template or not config:
            return {"error": "Template o configurazione non trovati"}
        
        # Prepara il contesto per il prompt
        from models import ExcelFile
        excel_file = ExcelFile.query.get(file_id)
        
        context = {
            'content': self.format_content_for_prompt(cells),
            'question': question,
            'file_name': excel_file.original_filename if excel_file else f"File {file_id}",
            'total_responses': len(cells),
            'response_count': len(cells)
        }
        
        # Genera il prompt processato
        processed_prompt = template.process_placeholders(context)
        
        return {
            'cells_count': len(cells),
            'template_name': template.name,
            'template_category': template.category,
            'config_name': config.name,
            'config_provider': config.provider,
            'processed_prompt': processed_prompt,
            'expected_labels': template.expected_labels_list,
            'cells_preview': [
                {
                    'id': cell.id,
                    'text': cell.text_content[:100] + "..." if len(cell.text_content) > 100 else cell.text_content,
                    'has_annotations': len(cell.annotations) > 0
                }
                for cell in cells[:10]  # Mostra solo i primi 10
            ]
        }
    
    def execute_bulk_annotation(self, file_id: int, question: str, template_id: int,
                              config_id: int, options: Dict[str, Any],
                              user_id: int = 1) -> Dict[str, Any]:
        """
        Esegue l'annotazione batch
        
        Returns:
            Dizionario con risultati dell'operazione
        """
        try:
            # Recupera i dati necessari
            cells = self.get_cells_by_criteria(file_id, question, options)
            template = PromptTemplate.query.get(template_id)
            config = AIConfiguration.query.get(config_id)
            
            if not template or not config:
                return {"success": False, "error": "Template o configurazione non trovati"}
            
            if not cells:
                return {"success": False, "error": "Nessuna cella da processare"}
            
            # Prepara il contesto per il prompt
            from models import ExcelFile
            excel_file = ExcelFile.query.get(file_id)
            
            context = {
                'content': self.format_content_for_prompt(cells),
                'question': question,
                'file_name': excel_file.original_filename if excel_file else f"File {file_id}",
                'total_responses': len(cells),
                'response_count': len(cells)
            }
            
            # Genera il prompt processato
            processed_prompt = template.process_placeholders(context)
            
            # Invia all'AI
            response = self.ai_service.generate_response(processed_prompt, config)
            
            if not response or not response.get('success'):
                return {"success": False, "error": f"Errore AI: {response.get('error', 'Risposta vuota')}"}
            
            # Parsa la risposta dell'AI
            ai_response_text = response.get('response', '')
            parsed_annotations = self.parse_ai_response(ai_response_text)
            
            if not parsed_annotations:
                return {"success": False, "error": "Impossibile parsare la risposta AI"}
            
            # Crea le annotazioni nel database
            created_annotations = self.create_annotations_from_ai_response(
                parsed_annotations, cells, template_id, config_id, user_id
            )
            
            return {
                "success": True,
                "cells_processed": len(cells),
                "annotations_created": len(created_annotations),
                "template_used": template.name,
                "config_used": config.name
            }
            
        except Exception as e:
            return {"success": False, "error": f"Errore durante l'annotazione: {str(e)}"}
    
    def parse_ai_response(self, ai_response: str) -> Optional[List[Dict[str, Any]]]:
        """
        Parsa la risposta dell'AI in formato JSON

        Returns:
            Lista di annotazioni parsate o None se il parsing fallisce
        """
        def extract_json_object(text: str) -> Optional[str]:
            """Estrae il primo oggetto JSON bilanciando le parentesi graffe."""
            start = text.find('{')
            if start == -1:
                return None
            depth = 0
            for i, ch in enumerate(text[start:], start):
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        return text[start:i + 1]
            return None

        try:
            json_str = extract_json_object(ai_response)
            if not json_str:
                return None

            parsed = json.loads(json_str)

            if 'annotations' not in parsed:
                return None

            return parsed['annotations']

        except (json.JSONDecodeError, ValueError) as e:
            print(f"Errore nel parsing JSON: {e}")
            return None
    
    def create_annotations_from_ai_response(self, annotations_data: List[Dict[str, Any]],
                                          cells: List[TextCell], template_id: int,
                                          config_id: int, user_id: int = 1) -> List[CellAnnotation]:
        """
        Crea le annotazioni nel database dalla risposta AI
        
        Returns:
            Lista delle annotazioni create
        """
        created_annotations = []
        cells_by_id = {cell.id: cell for cell in cells}
        
        for annotation_data in annotations_data:
            try:
                response_id = annotation_data.get('response_id')
                if not response_id or response_id not in cells_by_id:
                    continue
                
                labels = annotation_data.get('labels', [])
                if not labels:
                    continue
                
                # Crea annotazioni per ogni etichetta
                for label_data in labels:
                    if isinstance(label_data, dict):
                        label_name = label_data.get('name')
                        confidence = label_data.get('confidence', 0.5)
                        reasoning = label_data.get('reasoning', '')
                    else:
                        # Fallback se l'etichetta è una stringa
                        label_name = str(label_data)
                        confidence = 0.5
                        reasoning = ''
                    
                    if not label_name:
                        continue
                    
                    # Usa solo etichette canoniche attive (niente creazione automatica tassonomia)
                    label = Label.query.filter(
                        Label.name == label_name,
                        Label.is_active == True,  # noqa: E712
                        Label.merged_into_label_id.is_(None)
                    ).first()
                    if not label:
                        continue
                    if label.category_obj and (not label.category_obj.is_active or label.category_obj.merged_into_category_id is not None):
                        continue
                    
                    # Crea l'annotazione
                    annotation = CellAnnotation(
                        text_cell_id=response_id,
                        label_id=label.id,
                        user_id=user_id,
                        is_ai_generated=True,
                        ai_confidence=confidence,
                        ai_reasoning=reasoning,
                        status='pending_review',
                        created_by_prompt_template=template_id
                    )
                    
                    db.session.add(annotation)
                    created_annotations.append(annotation)
                
            except Exception as e:
                print(f"Errore nella creazione dell'annotazione: {e}")
                continue
        
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Errore nel commit delle annotazioni: {e}")
            return []
        
        return created_annotations
    
    def get_prompt_templates(self, category: Optional[str] = None) -> List[PromptTemplate]:
        """Recupera i template di prompt disponibili"""
        query = PromptTemplate.query.filter_by(is_active=True)
        
        if category:
            query = query.filter_by(category=category)
        
        return query.order_by(PromptTemplate.category, PromptTemplate.name).all()
    
    def get_ai_configurations(self, active_only: bool = True) -> List[AIConfiguration]:
        """Recupera le configurazioni AI disponibili"""
        query = AIConfiguration.query
        
        if active_only:
            query = query.filter_by(is_active=True)
        
        return query.order_by(AIConfiguration.name).all()
