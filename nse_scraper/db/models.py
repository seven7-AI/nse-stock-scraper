from sqlalchemy import Column, DateTime, Float, String, func
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class StockData(Base):
    __tablename__ = "stock_data"

    ticker_symbol = Column(String(20), primary_key=True, nullable=False)
    stock_name = Column(String(255), nullable=False)
    stock_price = Column(Float, nullable=False)
    stock_change = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
