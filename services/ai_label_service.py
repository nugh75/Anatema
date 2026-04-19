"""
Servizio per l'integrazione delle etichette con l'AI
"""

from models import Label, Category, db
from typing import List, Dict, Any
import json


class AILabelService:
    """Servizio per gestire l'integrazione delle etichette con l'AI"""
    
    @staticmethod
    def get_labels_for_ai() -> List[Dict[str, Any]]:
        """
        Ottiene tutte le etichette formattate per l'AI
        """
        labels = Label.query.filter(
            Label.is_active == True,  # noqa: E712
            Label.merged_into_label_id.is_(None)
        ).order_by(Label.name).all()
        
        labels_data = []
        for label in labels:
            if label.category_obj and (not label.category_obj.is_active or label.category_obj.merged_into_category_id is not None):
                continue

            category_name = label.category_obj.name if label.category_obj else 'Generale'
            labels_data.append({
                'id': label.id,
                'name': label.name,
                'description': label.description or '',
                'category': category_name,
                'color': label.color,
                'usage_count': len(label.annotations)
            })
        
        return labels_data
    
    @staticmethod
    def get_categories_for_ai() -> List[Dict[str, Any]]:
        """
        Ottiene tutte le categorie con le relative etichette per l'AI
        """
        categories = Category.query.filter(
            Category.is_active == True,  # noqa: E712
            Category.merged_into_category_id.is_(None)
        ).order_by(Category.name).all()
        
        categories_data = []
        for category in categories:
            labels_in_category = Label.query.filter(
                Label.category_id == category.id,
                Label.is_active == True,  # noqa: E712
                Label.merged_into_label_id.is_(None)
            ).order_by(Label.name).all()
            
            category_data = {
                'id': category.id,
                'name': category.name,
                'description': category.description or '',
                'color': category.color,
                'label_count': len(labels_in_category),
                'labels': []
            }
            
            for label in labels_in_category:
                category_data['labels'].append({
                    'id': label.id,
                    'name': label.name,
                    'description': label.description or '',
                    'color': label.color,
                    'usage_count': len(label.annotations)
                })
            
            categories_data.append(category_data)
        
        return categories_data
    
    @staticmethod
    def get_ai_annotation_prompt() -> str:
        """
        Genera un prompt per l'AI con tutte le etichette disponibili
        """
        categories = AILabelService.get_categories_for_ai()
        
        prompt_parts = [
            "Sei un assistente esperto nell'analisi tematica di testi.",
            "Devi analizzare le risposte testuali e assegnare le etichette più appropriate.",
            "",
            "ETICHETTE DISPONIBILI:"
        ]
        
        for category in categories:
            if category['labels']:
                prompt_parts.append(f"\n=== {category['name']} ===")
                if category['description']:
                    prompt_parts.append(f"({category['description']})")
                
                for label in category['labels']:
                    description = f" - {label['description']}" if label['description'] else ""
                    prompt_parts.append(f"• {label['name']}{description}")
        
        prompt_parts.extend([
            "",
            "ISTRUZIONI:",
            "1. Analizza attentamente il testo fornito",
            "2. Identifica i temi principali e le sfumature",
            "3. Assegna 1-5 etichette più appropriate dal set disponibile",
            "4. Preferisci etichette specifiche a quelle generiche",
            "5. Considera sia il contenuto esplicito che quello implicito",
            "",
            "FORMATO RISPOSTA:",
            "Rispondi SOLO con un JSON nel formato:",
            '{"labels": [{"id": ID_ETICHETTA, "name": "NOME_ETICHETTA", "confidence": CONFIDENZA_0_1}]}',
            "",
            "TESTO DA ANALIZZARE:"
        ])
        
        return "\n".join(prompt_parts)
    
    @staticmethod
    def get_ai_batch_annotation_prompt(texts: List[str]) -> str:
        """
        Genera un prompt per l'annotazione in batch di più testi
        """
        base_prompt = AILabelService.get_ai_annotation_prompt()
        
        batch_prompt = base_prompt.replace(
            "TESTO DA ANALIZZARE:",
            "TESTI DA ANALIZZARE (in batch):"
        )
        
        batch_prompt += "\n\n"
        
        for i, text in enumerate(texts, 1):
            batch_prompt += f"TESTO {i}:\n{text}\n\n"
        
        batch_prompt += """
FORMATO RISPOSTA PER BATCH:
Rispondi SOLO con un JSON nel formato:
{
  "annotations": [
    {
      "text_index": 1,
      "labels": [{"id": ID_ETICHETTA, "name": "NOME_ETICHETTA", "confidence": CONFIDENZA_0_1}]
    },
    {
      "text_index": 2,
      "labels": [{"id": ID_ETICHETTA, "name": "NOME_ETICHETTA", "confidence": CONFIDENZA_0_1}]
    }
  ]
}
"""
        
        return batch_prompt
    
    @staticmethod
    def validate_ai_response(response_data: Dict[str, Any]) -> bool:
        """
        Valida la risposta dell'AI per assicurarsi che sia nel formato corretto
        """
        try:
            if 'labels' in response_data:
                # Risposta singola
                labels = response_data['labels']
                if not isinstance(labels, list):
                    return False
                
                for label in labels:
                    if not isinstance(label, dict):
                        return False
                    if 'id' not in label or 'name' not in label:
                        return False
                    if not isinstance(label['id'], int):
                        return False
                    
                    # Verifica che l'etichetta esista ed sia canonica attiva
                    existing = Label.query.get(label['id'])
                    if not existing or not existing.is_active or existing.merged_into_label_id is not None:
                        return False
                
                return True
                
            elif 'annotations' in response_data:
                # Risposta batch
                annotations = response_data['annotations']
                if not isinstance(annotations, list):
                    return False
                
                for annotation in annotations:
                    if not isinstance(annotation, dict):
                        return False
                    if 'text_index' not in annotation or 'labels' not in annotation:
                        return False
                    if not isinstance(annotation['text_index'], int):
                        return False
                    
                    # Valida le etichette
                    if not AILabelService.validate_ai_response({'labels': annotation['labels']}):
                        return False
                
                return True
            
            return False
            
        except Exception:
            return False
    
    @staticmethod
    def get_label_statistics() -> Dict[str, Any]:
        """
        Ottiene statistiche sull'utilizzo delle etichette per l'AI
        """
        labels = Label.query.filter(
            Label.is_active == True,  # noqa: E712
            Label.merged_into_label_id.is_(None)
        ).all()
        categories = Category.query.filter(
            Category.is_active == True,  # noqa: E712
            Category.merged_into_category_id.is_(None)
        ).all()
        
        stats = {
            'total_labels': len(labels),
            'total_categories': len(categories),
            'labels_by_category': {},
            'most_used_labels': [],
            'least_used_labels': [],
            'usage_distribution': {}
        }
        
        # Statistiche per categoria
        for category in categories:
            category_labels = Label.query.filter(
                Label.category_id == category.id,
                Label.is_active == True,  # noqa: E712
                Label.merged_into_label_id.is_(None)
            ).all()
            stats['labels_by_category'][category.name] = {
                'count': len(category_labels),
                'labels': [label.name for label in category_labels]
            }
        
        # Etichette più e meno usate
        labels_with_usage = [(label, len(label.annotations)) for label in labels]
        labels_with_usage.sort(key=lambda x: x[1], reverse=True)
        
        stats['most_used_labels'] = [
            {'name': label.name, 'usage': usage} 
            for label, usage in labels_with_usage[:10]
        ]
        
        stats['least_used_labels'] = [
            {'name': label.name, 'usage': usage} 
            for label, usage in labels_with_usage[-10:] if usage == 0
        ]
        
        # Distribuzione d'uso
        usage_counts = [usage for _, usage in labels_with_usage]
        stats['usage_distribution'] = {
            'max': max(usage_counts) if usage_counts else 0,
            'min': min(usage_counts) if usage_counts else 0,
            'avg': sum(usage_counts) / len(usage_counts) if usage_counts else 0,
            'unused_count': sum(1 for usage in usage_counts if usage == 0)
        }
        
        return stats
    
    @staticmethod
    def get_recommended_labels(text: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Suggerisce etichette basate sull'analisi del testo (implementazione semplificata)
        """
        # Implementazione semplificata basata su parole chiave
        # In una versione avanzata, questo potrebbe usare machine learning
        
        text_lower = text.lower()
        suggestions = []
        
        labels = Label.query.filter(
            Label.is_active == True,  # noqa: E712
            Label.merged_into_label_id.is_(None)
        ).all()
        for label in labels:
            score = 0
            
            # Punteggio basato sulla corrispondenza del nome
            if label.name.lower() in text_lower:
                score += 10
            
            # Punteggio basato sulla descrizione
            if label.description:
                description_words = label.description.lower().split()
                for word in description_words:
                    if len(word) > 3 and word in text_lower:
                        score += 2
            
            # Punteggio basato sulla categoria
            if label.category_obj:
                category_name = label.category_obj.name.lower()
                if category_name in text_lower:
                    score += 5
            
            if score > 0:
                suggestions.append({
                    'id': label.id,
                    'name': label.name,
                    'description': label.description,
                    'category': label.category_obj.name if label.category_obj else 'Generale',
                    'score': score,
                    'confidence': min(score / 10, 1.0)
                })
        
        # Ordina per punteggio e limita i risultati
        suggestions.sort(key=lambda x: x['score'], reverse=True)
        return suggestions[:limit]
