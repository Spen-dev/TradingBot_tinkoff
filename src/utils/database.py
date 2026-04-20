"""SQLite database for trade history"""

import os
import sqlite3
import json
from datetime import datetime
from typing import Dict, List, Optional
from contextlib import contextmanager

class SecureDatabase:
    """Thread-safe SQLite database"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = None
        self.logger = None
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()
    
    def set_logger(self, logger):
        """Устанавливает логгер для базы данных"""
        self.logger = logger
    
    def _init_db(self):
        """Initialize database tables with all required columns"""
        with self._get_connection() as conn:
            # Trades table with all columns
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME,
                    ticker TEXT,
                    direction TEXT,
                    quantity REAL,
                    price REAL,
                    amount REAL,
                    commission REAL,
                    source TEXT,
                    status TEXT,
                    error TEXT,
                    order_id TEXT,
                    figi TEXT
                )
            """)
            
            # Portfolio snapshots
            conn.execute("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME,
                    total_value REAL,
                    cash REAL,
                    positions TEXT
                )
            """)
            
            # Daily statistics
            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE,
                    total_trades INTEGER,
                    buy_count INTEGER,
                    sell_count INTEGER,
                    total_volume REAL,
                    total_commission REAL,
                    profit_loss REAL
                )
            """)
            
            # Indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp ON snapshots(timestamp)")
            
            # Check if we need to migrate existing table
            cursor = conn.execute("PRAGMA table_info(trades)")
            columns = [col[1] for col in cursor.fetchall()]
            
            # Add missing columns if table already exists
            if 'order_id' not in columns:
                try:
                    conn.execute("ALTER TABLE trades ADD COLUMN order_id TEXT")
                    if self.logger:
                        self.logger.info("✅ Added order_id column to trades table")
                except:
                    pass
            
            if 'figi' not in columns:
                try:
                    conn.execute("ALTER TABLE trades ADD COLUMN figi TEXT")
                    if self.logger:
                        self.logger.info("✅ Added figi column to trades table")
                except:
                    pass
            
            if self.logger:
                self.logger.debug("Database initialized successfully")
    
    @contextmanager
    def _get_connection(self):
        """Get database connection with context manager"""
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    
    def save_trade(self, trade: Dict):
        """Save trade to database"""
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO trades 
                    (timestamp, ticker, direction, quantity, price, amount, commission, source, status, error, order_id, figi)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trade.get('timestamp', datetime.now()),
                    trade.get('ticker'),
                    trade.get('direction'),
                    trade.get('quantity', 0),
                    trade.get('price', 0),
                    trade.get('amount', 0) or trade.get('quantity', 0) * trade.get('price', 0),
                    trade.get('commission', 0),
                    trade.get('source', 'tinkoff'),
                    trade.get('status', 'unknown'),
                    trade.get('error', ''),
                    trade.get('order_id', ''),
                    trade.get('figi', '')
                ))
                
                if self.logger:
                    self.logger.debug(f"Trade saved: {trade.get('ticker')} {trade.get('direction')}")
                    
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error saving trade: {e}")
    
    def save_snapshot(self, total_value: float, cash: float, positions: Dict):
        """Save portfolio snapshot"""
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO snapshots (timestamp, total_value, cash, positions)
                    VALUES (?, ?, ?, ?)
                """, (datetime.now(), total_value, cash, json.dumps(positions)))
                
                if self.logger:
                    self.logger.debug(f"Snapshot saved: total={total_value:.2f}, cash={cash:.2f}")
                    
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error saving snapshot: {e}")
    
    def save_daily_stats(self, date: str, stats: Dict):
        """Save daily statistics"""
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO daily_stats 
                    (date, total_trades, buy_count, sell_count, total_volume, total_commission, profit_loss)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    date,
                    stats.get('total_trades', 0),
                    stats.get('buy_count', 0),
                    stats.get('sell_count', 0),
                    stats.get('total_volume', 0),
                    stats.get('total_commission', 0),
                    stats.get('profit_loss', 0)
                ))
                
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error saving daily stats: {e}")
    
    def get_last_trades(self, limit: int = 10) -> List[Dict]:
        """Get last N trades"""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute("""
                    SELECT * FROM trades 
                    ORDER BY timestamp DESC 
                    LIMIT ?
                """, (limit,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error getting last trades: {e}")
            return []
    
    def get_trades_by_date(self, date: str) -> List[Dict]:
        """Get trades for specific date"""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute("""
                    SELECT * FROM trades 
                    WHERE DATE(timestamp) = ?
                    ORDER BY timestamp
                """, (date,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error getting trades by date: {e}")
            return []
    
    def get_trades_by_ticker(self, ticker: str, limit: int = 50) -> List[Dict]:
        """Get trades for specific ticker"""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute("""
                    SELECT * FROM trades 
                    WHERE ticker = ?
                    ORDER BY timestamp DESC 
                    LIMIT ?
                """, (ticker, limit))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error getting trades by ticker: {e}")
            return []
    
    def get_portfolio_history(self, days: int = 30) -> List[Dict]:
        """Get portfolio history for last N days"""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute("""
                    SELECT * FROM snapshots 
                    WHERE timestamp >= datetime('now', '-' || ? || ' days')
                    ORDER BY timestamp
                """, (days,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error getting portfolio history: {e}")
            return []
    
    def get_statistics(self) -> Dict:
        """Get overall statistics"""
        try:
            with self._get_connection() as conn:
                # Total trades
                cursor = conn.execute("SELECT COUNT(*) as count FROM trades")
                total_trades = cursor.fetchone()['count']
                
                # Total buy volume
                cursor = conn.execute("""
                    SELECT SUM(amount) as total FROM trades 
                    WHERE direction = 'buy'
                """)
                buy_volume = cursor.fetchone()['total'] or 0
                
                # Total sell volume
                cursor = conn.execute("""
                    SELECT SUM(amount) as total FROM trades 
                    WHERE direction = 'sell'
                """)
                sell_volume = cursor.fetchone()['total'] or 0
                
                # Total commission
                cursor = conn.execute("SELECT SUM(commission) as total FROM trades")
                total_commission = cursor.fetchone()['total'] or 0
                
                # Most traded ticker
                cursor = conn.execute("""
                    SELECT ticker, COUNT(*) as count 
                    FROM trades 
                    GROUP BY ticker 
                    ORDER BY count DESC 
                    LIMIT 1
                """)
                most_traded = cursor.fetchone()
                
                return {
                    'total_trades': total_trades,
                    'buy_volume': buy_volume,
                    'sell_volume': sell_volume,
                    'total_volume': buy_volume + sell_volume,
                    'total_commission': total_commission,
                    'most_traded_ticker': most_traded['ticker'] if most_traded else None,
                    'most_traded_count': most_traded['count'] if most_traded else 0
                }
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error getting statistics: {e}")
            return {}
    
    def get_daily_stats(self, days: int = 7) -> List[Dict]:
        """Get daily statistics for last N days"""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute("""
                    SELECT * FROM daily_stats 
                    ORDER BY date DESC 
                    LIMIT ?
                """, (days,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error getting daily stats: {e}")
            return []
    
    def close(self):
        """Close database connection"""
        try:
            if hasattr(self, 'conn') and self.conn:
                self.conn.close()
                self.conn = None
                if self.logger:
                    self.logger.debug("Database connection closed")
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error closing database: {e}")
    
    def vacuum(self):
        """Optimize database (remove deleted space)"""
        try:
            with self._get_connection() as conn:
                conn.execute("VACUUM")
                if self.logger:
                    self.logger.debug("Database vacuum completed")
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error during vacuum: {e}")
    
    def backup(self, backup_path: str):
        """Create database backup"""
        try:
            import shutil
            shutil.copy2(self.db_path, backup_path)
            if self.logger:
                self.logger.info(f"Database backup created: {backup_path}")
            return True
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error creating backup: {e}")
            return False
    
    def clear_old_data(self, days: int = 90):
        """Clear data older than specified days"""
        try:
            with self._get_connection() as conn:
                # Delete old trades
                conn.execute("""
                    DELETE FROM trades 
                    WHERE timestamp < datetime('now', '-' || ? || ' days')
                """, (days,))
                
                # Delete old snapshots
                conn.execute("""
                    DELETE FROM snapshots 
                    WHERE timestamp < datetime('now', '-' || ? || ' days')
                """, (days,))
                
                deleted_trades = conn.total_changes
                if self.logger:
                    self.logger.info(f"Cleared {deleted_trades} old records")
                    
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error clearing old data: {e}")