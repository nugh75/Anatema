#!/usr/bin/env python3
"""
Script per fare merge selettivo tra database produzione e sviluppo
Mantiene le tabelle forum in sviluppo, aggiorna i dati comuni da produzione
"""

import sqlite3
import shutil
from pathlib import Path
from datetime import datetime

def merge_databases():
    """Merge selettivo dei database"""
    
    # Percorsi dei database
    project_root = Path('/home/nugh75/Git/analisi-mu')
    prod_db = project_root / 'instance' / 'analisi_mu.db'
    dev_db = project_root / 'instance_dev' / 'analisi_mu_dev.db'
    
    print("🔄 Avvio merge selettivo database produzione → sviluppo")
    print(f"📊 Database produzione: {prod_db}")
    print(f"🛠️  Database sviluppo: {dev_db}")
    
    # Verifica che entrambi i database esistano
    if not prod_db.exists():
        print(f"❌ Database produzione non trovato: {prod_db}")
        return False
        
    if not dev_db.exists():
        print(f"❌ Database sviluppo non trovato: {dev_db}")
        return False
    
    # Backup del database di sviluppo
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = dev_db.with_suffix(f'.backup_{timestamp}.db')
    print(f"💾 Creando backup: {backup_path}")
    shutil.copy2(dev_db, backup_path)
    
    try:
        # Connessioni ai database
        prod_conn = sqlite3.connect(prod_db)
        dev_conn = sqlite3.connect(dev_db)
        
        # Tabelle da copiare da produzione (dati che cambiano)
        tables_to_copy = [
            'user',
            'excel_file', 
            'text_cell',
            'annotation',
            'label',
            'category'
        ]
        
        # Tabelle da mantenere in sviluppo (nuove funzionalità)
        tables_to_keep = [
            'forum_category',
            'forum_post', 
            'forum_comment'
        ]
        
        print(f"📋 Tabelle da copiare da produzione: {', '.join(tables_to_copy)}")
        print(f"🔒 Tabelle da mantenere in sviluppo: {', '.join(tables_to_keep)}")
        
        # Per ogni tabella da copiare
        for table in tables_to_copy:
            print(f"🔄 Processando tabella: {table}")
            
            # Verifica se la tabella esiste in produzione
            cursor = prod_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", 
                (table,)
            )
            
            if not cursor.fetchone():
                print(f"⚠️  Tabella {table} non esiste in produzione, salto")
                continue
            
            # Svuota la tabella in sviluppo
            dev_conn.execute(f"DELETE FROM {table}")
            print(f"   🗑️  Svuotata tabella {table} in sviluppo")
            
            # Copia i dati da produzione
            prod_cursor = prod_conn.execute(f"SELECT * FROM {table}")
            columns = [desc[0] for desc in prod_cursor.description]
            
            rows_copied = 0
            for row in prod_cursor:
                placeholders = ','.join(['?' for _ in columns])
                dev_conn.execute(
                    f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
                    row
                )
                rows_copied += 1
            
            print(f"   ✅ Copiati {rows_copied} record in {table}")
        
        # Commit delle modifiche
        dev_conn.commit()
        print("💾 Commit delle modifiche completato")
        
        # Verifica integrità
        print("🔍 Verifica integrità database...")
        
        # Conta record nelle tabelle principali
        for table in ['user', 'excel_file', 'annotation']:
            try:
                cursor = dev_conn.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                print(f"   📊 {table}: {count} record")
            except:
                print(f"   ⚠️  Errore nel contare {table}")
        
        # Verifica tabelle forum (devono essere mantenute)
        for table in tables_to_keep:
            try:
                cursor = dev_conn.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                print(f"   🔒 {table} (mantenuta): {count} record")
            except:
                print(f"   ⚠️  Tabella forum {table} non esiste o errore")
        
        print("✅ Merge completato con successo!")
        print(f"💾 Backup salvato in: {backup_path}")
        
        return True
        
    except Exception as e:
        print(f"❌ Errore durante il merge: {e}")
        
        # Ripristina il backup in caso di errore
        print("🔄 Ripristino backup...")
        shutil.copy2(backup_path, dev_db)
        print("✅ Backup ripristinato")
        
        return False
        
    finally:
        # Chiudi connessioni
        try:
            prod_conn.close()
            dev_conn.close()
        except:
            pass

if __name__ == '__main__':
    success = merge_databases()
    if success:
        print("\n🎉 Database merge completato!")
        print("📝 Puoi ora riavviare il server di sviluppo con: python start_dev.py")
    else:
        print("\n❌ Merge fallito, controllare gli errori sopra")
