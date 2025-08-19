from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy.dialects.sqlite import JSON

db = SQLAlchemy()

class ETF(db.Model):
    __tablename__ = 'etfs'
    
    id = db.Column(db.Integer, primary_key=True)
    ticker = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    current_price = db.Column(db.Float)
    current_yield = db.Column(db.Float)
    frequency = db.Column(db.String(20))  # monthly, quarterly, etc.
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    prices = db.relationship('ETFPrice', backref='etf', lazy='dynamic', cascade='all, delete-orphan')
    dividends = db.relationship('ETFDividend', backref='etf', lazy='dynamic', cascade='all, delete-orphan')
    splits = db.relationship('ETFSplit', backref='etf', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<ETF {self.ticker}: {self.name}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'ticker': self.ticker,
            'name': self.name,
            'current_price': self.current_price,
            'current_yield': self.current_yield,
            'frequency': self.frequency,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class ETFPrice(db.Model):
    __tablename__ = 'etf_prices'
    
    id = db.Column(db.Integer, primary_key=True)
    etf_id = db.Column(db.Integer, db.ForeignKey('etfs.id'), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    close_price = db.Column(db.Float, nullable=False)  # Oryginalna cena
    normalized_close_price = db.Column(db.Float, nullable=False)  # Znormalizowana cena
    split_ratio_applied = db.Column(db.Float, default=1.0)  # Współczynnik splitu
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('etf_id', 'date', name='_etf_date_uc'),)
    
    def __repr__(self):
        return f'<ETFPrice {self.etf_id} {self.date}: {self.close_price} -> {self.normalized_close_price}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'etf_id': self.etf_id,
            'date': self.date.isoformat() if self.date else None,
            'close_price': self.close_price,
            'normalized_close_price': self.normalized_close_price,
            'split_ratio_applied': self.split_ratio_applied,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class ETFDividend(db.Model):
    __tablename__ = 'etf_dividends'
    
    id = db.Column(db.Integer, primary_key=True)
    etf_id = db.Column(db.Integer, db.ForeignKey('etfs.id'), nullable=False, index=True)
    payment_date = db.Column(db.Date, nullable=False, index=True)
    ex_date = db.Column(db.Date, index=True)
    amount = db.Column(db.Float, nullable=False)  # Oryginalna kwota
    normalized_amount = db.Column(db.Float, nullable=False)  # Znormalizowana kwota
    split_ratio_applied = db.Column(db.Float, default=1.0)  # Współczynnik splitu
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('etf_id', 'payment_date', name='_etf_payment_date_uc'),)
    
    def __repr__(self):
        return f'<ETFDividend {self.etf_id} {self.payment_date}: {self.amount} -> {self.normalized_amount}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'etf_id': self.etf_id,
            'payment_date': self.payment_date.isoformat() if self.payment_date else None,
            'ex_date': self.ex_date.isoformat() if self.ex_date else None,
            'amount': self.amount,
            'normalized_amount': self.normalized_amount,
            'split_ratio_applied': self.split_ratio_applied,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class ETFSplit(db.Model):
    __tablename__ = 'etf_splits'
    
    id = db.Column(db.Integer, primary_key=True)
    etf_id = db.Column(db.Integer, db.ForeignKey('etfs.id'), nullable=False, index=True)
    split_date = db.Column(db.Date, nullable=False, index=True)
    split_ratio = db.Column(db.Float, nullable=False)  # np. 3.0 dla 3:1 split
    description = db.Column(db.String(200))  # np. "3:1 Stock Split"
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('etf_id', 'split_date', name='_etf_split_date_uc'),)
    
    def __repr__(self):
        return f'<ETFSplit {self.etf_id} {self.split_date}: {self.split_ratio}:1>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'etf_id': self.etf_id,
            'split_date': self.split_date.isoformat() if self.split_date else None,
            'split_ratio': self.split_ratio,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class SystemLog(db.Model):
    __tablename__ = 'system_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    action = db.Column(db.String(100), nullable=False)
    details = db.Column(db.Text)
    level = db.Column(db.String(20), default='INFO')  # INFO, WARNING, ERROR
    metadata_json = db.Column(JSON)
    
    def __repr__(self):
        return f'<SystemLog {self.timestamp}: {self.action}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'action': self.action,
            'details': self.details,
            'level': self.level,
            'metadata': self.metadata_json
        }

class APILimit(db.Model):
    __tablename__ = 'api_limits'
    
    id = db.Column(db.Integer, primary_key=True)
    api_type = db.Column(db.String(20), unique=True, nullable=False, index=True)  # 'fmp', 'eodhd', 'tiingo'
    current_count = db.Column(db.Integer, default=0, nullable=False)
    daily_limit = db.Column(db.Integer, nullable=False)
    last_reset = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<APILimit {self.api_type}: {self.current_count}/{self.daily_limit}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'api_type': self.api_type,
            'current_count': self.current_count,
            'daily_limit': self.daily_limit,
            'last_reset': self.last_reset.isoformat() if self.last_reset else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
