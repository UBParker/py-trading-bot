#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jan  6 19:41:08 2023

@author: maxime
"""

from trading_bot.settings import _settings
from vectorbtpro.data.custom import RemoteData
from vectorbtpro import _typing as tp
import warnings
import math
from ib_insync import MarketOrder, util
from core.indicators import rel_dif
from django.db.models import Q
from django.utils import timezone

import vectorbtpro as vbt
import numpy as np
import decimal

import logging
logger = logging.getLogger(__name__)
logger_trade = logging.getLogger('trade')

from orders.models import (Action, Order, ActionCategory, StockEx, Excluded, Strategy,
                           action_to_etf,
                           get_pf, get_order_capital, period_YF_to_ib,
                           exchange_to_index_symbol
                           )
#Module to handle IB connection
ib_cfg={"localhost":_settings["IB_LOCALHOST"],"port":_settings["IB_PORT"]}
ib_global={"connected":False, "client":None}

class IBData(RemoteData):
    @classmethod
    def connect(cls):
        if not cls.client.isConnected():
            clientID=1
            while clientID<=100:
                try:
                    cls.client.connect(host=ib_cfg['localhost'], port=ib_cfg['port'], clientId=clientID)
                    break
                except:                    
                    clientID+=1
                    pass
        if cls.client.isConnected():
            ib_global["connected"]=True
        else:
            warnings.warn("connection to IB failed, check that IB is started")   
            
    @classmethod
    def resolve_client(cls, client: tp.Optional[tp.Any] = None, **client_config) -> tp.Any:
        from ib_insync import IB
        import asyncio

        if client is None and "cls.client" not in locals(): #create a new connection
            if ib_global["client"] is None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                cls.client=IB()
                cls.connect()
                ib_global["client"]=cls.client
            else:
                cls.client=ib_global["client"]
        elif client is not None:
            cls.client=client
        #check everytime
        if cls.client.isConnected():
            ib_global["connected"]=True
        else:
            ib_global["connected"]=False
        
        return cls.client

    @classmethod 
    def get_contract_ib(cls, symbol,exchange,index):
        from ib_insync import Stock, Index
        if index:
            return Index(exchange=exchange,symbol=symbol)
        elif exchange in ["NASDAQ","NYSE"]:
            return Stock(symbol,"SMART", primaryExchange=exchange)
        else:
            return Stock(symbol,exchange)

    @classmethod
    def fetch_symbol(
        cls,
        symbol: str, 
        client: tp.Optional[tp.Any] = None,
        client_config: tp.KwargsLike = None,
        period: tp.Optional[str] = None,
        start: tp.Optional[tp.DatetimeLike] = None,
        end: tp.Optional[tp.DatetimeLike] = None,
        timeframe: tp.Optional[str] = None,
        indexes: tp.Optional[dict] = None,
        exchanges: tp.Optional[dict] = None,
        ) -> tp.Any:

        from ib_insync import util
        
        exchange="SMART" #default
        if exchanges is not None:
            if symbol in exchanges:
                exchange=exchanges[symbol]
                
        index=False
        if indexes is not None:
            if symbol in indexes:
                index=indexes[symbol]        
        
        if client_config is None:
            client_config = {}
        cls.resolve_client(client=client, **client_config)

        if ib_global["connected"]:
            contract=cls.get_contract_ib(symbol,exchange,index)
            #check period and timeframe
            bars = cls.client.reqHistoricalData(
                    contract,
                    endDateTime='',
                    durationStr=period, #"10 D","1 M"
                    barSizeSetting=timeframe, #"1 day", "1 min"
                    whatToShow='TRADES',
                    useRTH=True,
                    formatDate=1)
            df=util.df(bars)
            
            if df is not None:
                df.rename(
                    columns={
                        "date":"Date",
                        "open": "Open",
                        "high": "High",
                        "low": "Low",
                        "close": "Close",
                        "volume": "Volume",
                        "average":"Average",
                        "barCount": 'BarCount',
                    },
                    inplace=True,
                )
                df=df.set_index('Date')
            
            return df
        
    @classmethod
    def get_last_price(cls,contract):
        timeout=2
        t=0
        cls.resolve_client(client=None)
        m_data = cls.client.reqMktData(contract)
        while m_data.last != m_data.last and t<timeout:  #Wait until data is in. 
            t+=0.01
            cls.client.sleep(0.01)
        if t==timeout:
            m_data.last=0
        cls.client.cancelMktData(contract)
        return m_data.last
    
# Part customized for the bot
###IB management, moved to vbt principally

#decorator
def connect_ib(func):
    def wrapper(*args,**kwargs):
        kwargs['client'] = IBData.resolve_client(None)
        return func(*args,**kwargs)
    return wrapper

@connect_ib
def get_tradable_contract_ib(action,short,**kwargs):
    if action.ib_ticker()=="AAA":
        logger.info("stock "+action.ib_ticker() + " not found")
        return None
    else:
        if action.stock_ex.ib_auth:
            action=action_to_etf(action,short) #if index replace the index through the corresponding ETF
            return IBData.get_contract_ib(action.ib_ticker(),action.stock_ex.ib_ticker,False)
        else:
            logger.info("stock "+action.ib_ticker() + " not in authorized stock exchange")
            return None

@connect_ib
def retrieve_quantity(in_action, **kwargs):
    if kwargs['client'] and ib_global["connected"]:
        for pos in kwargs['client'].positions():
            contract=pos.contract
            if in_action.ib_ticker()==contract.localSymbol:
                return abs(pos.position), np.sign(pos.position)
    return 0, 0      
                    
@connect_ib
def retrieve_ib_pf(**kwargs):
    if kwargs['client'] and ib_global["connected"]:
        print("myIB retrieve")
        action=None
        pf=[]
        pf_short=[]
        
        for pos in kwargs['client'].positions():
            contract=pos.contract
            actions=Action.objects.filter(symbol__contains=contract.localSymbol)
            if len(actions)==0:
                action=None
            elif len(actions)==1:
                action=actions[0]
            else:
                for a in actions:
                    if a.ib_ticker()==contract.localSymbol:
                        action=a
            
            if action is not None:            
                if pos.position>0:
                    pf.append(action)
                else:
                    pf_short.append(action)

        return pf, pf_short
    else:
        return None, None

@connect_ib   
def check_enough_cash(order_size,**kwargs):
    if cash_balance(**kwargs)>=order_size:
        return True
    else:
        kwargs["currency"]="EUR" #fallback, if there is enough EUR, IB will convert
        if cash_balance(**kwargs)>=order_size:
            return True
        else:
            return False
        
@connect_ib        
def cash_balance(**kwargs):
    currency=kwargs.get('currency',"EUR")

    if kwargs['client'] and ib_global["connected"]:
        for v in kwargs['client'].accountValues():
            if v.tag == 'CashBalance' and v.currency==currency:
                return float(v.value)
    else:
        return 0

#for SL check
@connect_ib
def get_last_price(action,**kwargs):
    try:
        if kwargs['client'] and ib_global["connected"] and\
            (_settings["USE_IB_FOR_DATA"]["alerting"] and\
                               action.stock_ex.ib_auth and\
                                  action.symbol not in _settings["IB_STOCK_NO_PERMISSION"]):
            
            contract=IBData.get_contract_ib(action.ib_ticker(),action.stock_ex.ib_ticker,check_if_index(action))
            if contract is not None:
                cours_pres=IBData.get_last_price(contract)
        else: #YF
            cours=vbt.YFData.fetch([action.symbol], period="2d")
            cours_close=cours.get("Close")
            cours_pres=cours_close[action.symbol].iloc[-1]
    
        return cours_pres

    except Exception as e:
         logger.error(e, stack_info=True, exc_info=True)

#For alerting and TSL check        
@connect_ib  
def get_ratio(action,**kwargs):
    try:
        cours_pres=0
        cours_ref=0

        if ib_global["connected"] and kwargs['client']  and\
              (_settings["USE_IB_FOR_DATA"]["alerting"] and\
                                 action.stock_ex.ib_auth and\
                                  action.symbol not in _settings["IB_STOCK_NO_PERMISSION"]):
            
            contract=IBData.get_contract_ib(action.ib_ticker(),action.stock_ex.ib_ticker,check_if_index(action))
            if contract is not None:
                bars = kwargs['client'].reqHistoricalData(
                        contract,
                        endDateTime='',
                        durationStr="2 D", #"10 D","1 M"
                        barSizeSetting='1 day', #"1 day", "1 min"
                        whatToShow='TRADES',
                        useRTH=True,
                        formatDate=1)
                if len(bars)!=0:
                    df=util.df(bars)
                    cours_ref=df.iloc[0]["close"] #closing price of the day before
                    cours_pres=IBData.get_last_price(contract)
   
        else: #YF
            cours=vbt.YFData.fetch([action.symbol], period="2d")
            cours_close=cours.get("Close")
            cours_ref=cours_close[action.symbol].iloc[0]
            cours_pres=cours_close[action.symbol].iloc[-1]
                
        if cours_pres!=0 and cours_ref!=0:
            return rel_dif(cours_pres,cours_ref)*100
        else:
            return 0

    except Exception as e:
         logger.error(e, stack_info=True, exc_info=True)

@connect_ib  
def place(buy,action,short,**kwargs): 
    try:
        if kwargs['client'] and ib_global["connected"]:
            contract =get_tradable_contract_ib(action,short)
            
            if contract is None:
                return "", decimal.Decimal(1.0), decimal.Decimal(0.0)
            else:
                kwargs['client'].qualifyContracts(contract)
                quantity=kwargs.get("quantity",0)
                
                if buy:
                    if quantity==0:
                        order_size=kwargs.get("order_size",0)
                        last_price=IBData.get_last_price(contract)
                        quantity=math.floor(order_size/last_price)
                    
                    if short:
                        order = MarketOrder('SELL', quantity)
                    else:
                        order = MarketOrder('BUY', quantity)
                else:
                    
                    if short:
                        order = MarketOrder('BUY', quantity)
                    else:
                        order = MarketOrder('SELL', quantity)
                trade = kwargs['client'].placeOrder(contract, order)
                logger_trade.info("order sent to IB, action " + str(action)+", short: " + str(short) + ", quantity: "+str(quantity))
        
                max_time=20
                t=0
                
                while t<max_time:
                
                    kwargs['client'].sleep(1.0)
                    t+=1
    
                    if trade.orderStatus.status == 'Filled':
                        fill = trade.fills[-1]
                        logger_trade.info(f'{fill.time} - {fill.execution.side} {fill.contract.symbol} {fill.execution.shares} @ {fill.execution.avgPrice}')
                        price=fill.execution.avgPrice     
                        return decimal.Decimal(price), decimal.Decimal(quantity)
                    
                logger_trade.info("order not filled, pending")
                return decimal.Decimal(1.0), decimal.Decimal(1.0)
    except Exception as e:
         logger.error(e, stack_info=True, exc_info=True)


#better to have a separate function for reversing. Exit would not buy anything and would lead to double fees
#entry alone would not close the last order
def reverse_order_sub(symbol,strategy, exchange,short,use_IB,**kwargs): #convention short==True --> we go to short
    try:
        #type check necessary for indexes
        pf= get_pf(strategy, exchange,short,**kwargs) #destination portfolio
        pf_inv= get_pf(strategy, exchange,not short,**kwargs)
        ocap=get_order_capital(strategy, exchange,**kwargs)
        
        action=Action.objects.get(symbol=symbol)
        action=action_to_etf(action,short)
        
        c1 = Q(action=action)
        c2 = Q(active=True)
        orders=Order.objects.filter(c1 & c2)
        
        if use_IB:
            order_size=_settings["ORDER_SIZE"]
            enough_cash=check_enough_cash(order_size,currency=action.currency.symbol)
        else:
            enough_cash=True
        
        if len(orders)==0: #necessary for the first trade of a stock for instance, or if it was closed on a stop loss
            order=Order(action=action, pf=pf, short=short) #use full if you did the entry order manually...
            logger.info("order not found " + symbol+ ", created")
        else:
            order=orders[0]
            
        if use_IB:    
            order.quantity, sign=retrieve_quantity(action) #safer than looking in what we saved
        else:
            if order.short:
                sign=-1
            else:
                sign=1
        
        order.save()
        strategy_none, _ = Strategy.objects.get_or_create(name="none")
        
        if (symbol in pf.retrieve() ):
            logger.info(str(symbol) + " already in portfolio")
        if not enough_cash and not short:
            logger.info(str(symbol) + " order not executed, not enough cash available")
            print("Reversal order "+str(symbol) + "not executed, not enough cash available!!!!")
        
        if (symbol not in pf.retrieve() and 
            (ocap.capital>0 or _settings["BYPASS_ORDERCAPITAL_IF_IB"]) and
            enough_cash or short):
            
            #pf should be enough, but it is a double security
            if (short and sign<0) or (not short and sign>0):
                logger.info("pf correction performed, no order executed")
                pf.remove(action.symbol)
                pf_inv.append(action.symbol)       
                return False

            new_order=Order(action=action, pf=pf)
            
            if use_IB:
                logger_trade.info("place reverse order symbol: "+symbol+" , strategy: " + strategy + " short: "+str(short))
                if order.quantity==0: #for the first order
                    new_order.entering_price, _= place(True,
                                            action,
                                            short,
                                            order_size=order_size)
                else:
                    new_order.entering_price, _= place(True,
                                            action,
                                            short,
                                            quantity=order.quantity*2) #*2 to revert the order
                logger_trade.info("entering_price: "+ str(new_order.entering_price))
                new_order.quantity, _=retrieve_quantity(action)
                new_order.short=short
                
                logger_trade.info("sl" + str(kwargs.get("sl",False)))
                logger_trade.info("daily sl" + str(kwargs.get("daily_sl",False)))
                if kwargs.get("sl",False):
                    sl=kwargs.get("sl")
                    if short:
                        new_order.sl_threshold=order.entering_price*(1+sl)
                    else:
                        new_order.sl_threshold=order.entering_price*(1-sl)
                
                if new_order.entering_price is not None and order.entering_price is not None: 
                    order.profit=new_order.entering_price-order.entering_price
                    if order.entering_price != 0:
                        order.profit_percent=(new_order.entering_price/order.entering_price-1)*100
            else:
                new_order.entering_price=1.0 
                logger_trade.info("Manual reverse order symbol: "+symbol+" , strategy: " + strategy + " short: "+str(short))
                
            if kwargs.get("daily_sl",False):
                new_order.daily_sl_threshold=kwargs.get("daily_sl")
            
            order.exiting_date=timezone.now()
            order.active=False
            order.save()
            new_order.save()
            pf.append(action.symbol)
            pf_inv.remove(action.symbol)
            return True
        return False
    
    except Exception as e:
        logger.error(str(e) + "symbol: "+str(symbol), stack_info=True, exc_info=True)
        pass        

def exit_order_sub(symbol,strategy, exchange,short,use_IB,**kwargs):   
    #type check necessary for indexes
    try:
        pf= get_pf(strategy, exchange,short,**kwargs)
        ocap=get_order_capital(strategy, exchange,**kwargs)
               
        action=Action.objects.get(symbol=symbol)
        action=action_to_etf(action,short)
        
        if symbol in pf.retrieve():
            c1 = Q(action=action)
            c2 = Q(active=True)
            
            orders=Order.objects.filter(c1 & c2)
            if len(orders)==0:
                order=Order(action=action, pf=pf) #use full if you did the entry order manually...
                logger.info("order not found " + str(symbol) + " present position: "+ str(order.quantity))
                order.save()
            else:
                order=orders[0]
            
            if use_IB:    
                order.quantity, sign=retrieve_quantity(action) #safer than looking in what we saved
            #profit
            if use_IB and order.quantity>0:
                logger_trade.info("place exit order symbol: "+symbol+" , strategy: " + strategy + " short: "+str(short))
                order.exiting_price, quantity= place(False,
                                       action,
                                       short,
                                       quantity=order.quantity)
                
                if order.entering_price is not None: 
                    order.profit=order.exiting_price-order.entering_price
                    if order.entering_price != 0:
                        order.profit_percent=(order.exiting_price/order.entering_price-1)*100
            else:
                logger_trade.info("Manual exit order symbol: "+symbol+" , strategy: " + strategy + " short: "+str(short))
                
            order.exiting_date=timezone.now()
            order.active=False
            order.save()

            ocap.capital+=1
            ocap.save()
            pf.remove(symbol)
            return True
        else:
            logger.info(str(symbol) + " not found in portfolio for exit order")
        return False
    
    except Exception as e:
        logger.error(e, stack_info=True, exc_info=True)
        pass
    
def entry_order_sub(symbol,strategy, exchange,short,use_IB,**kwargs): 
    try:
        #type check necessary for indexes
        pf= get_pf(strategy, exchange,short,**kwargs)
        ocap=get_order_capital(strategy, exchange,**kwargs)
        action=Action.objects.get(symbol=symbol)
        
        if use_IB:
            order_size=_settings["ORDER_SIZE"]
            enough_cash=check_enough_cash(order_size,currency=action.currency.symbol)
        else:
            enough_cash=True

        strategy_none, _ = Strategy.objects.get_or_create(name="none")
        excluded, _=Excluded.objects.get_or_create(name="all",strategy=strategy_none) #list of actions completely excluded from entries
        if (symbol in pf.retrieve() ):
            logger.info(str(symbol) + " already in portfolio")
        if (symbol in excluded.retrieve() ):
            logger.info(str(symbol) + " excluded")    
        #if (ocap.capital==0):
            #print(symbol + " order not executed, no order capital available: " + ocap.name)
        if not enough_cash and not short:
            logger.info(str(symbol) + " order not executed, not enough cash available")
        
        if (symbol not in pf.retrieve() and 
            symbol not in excluded.retrieve() and  
            (ocap.capital>0 or _settings["BYPASS_ORDERCAPITAL_IF_IB"]) and
            enough_cash or short):

            order=Order(action=action, pf=pf, short=short)

            if use_IB:
                logger_trade.info("place entry order symbol: "+symbol+" , strategy: " + strategy + " short: "+str(short))
                order.entering_price, order.quantity= place(True,
                                        action,
                                        short,
                                        order_size=order_size)
                logger_trade.info("entering_price: "+ str(order.entering_price))
                logger_trade.info("sl" + str(kwargs.get("sl",False)))
                logger_trade.info("daily sl" + str(kwargs.get("daily_sl",False)))
                if kwargs.get("sl",False):
                    sl=kwargs.get("sl")
                    if short:
                        order.sl_threshold=order.entering_price*(1+sl)
                    else:
                        order.sl_threshold=order.entering_price*(1-sl)
            else:
                order.entering_price=1.0   
                logger_trade.info("Manual entry order symbol: "+symbol+" , strategy: " + strategy + " short: "+str(short))
                 
            if kwargs.get("daily_sl",False):
                order.daily_sl_threshold=kwargs.get("daily_sl")
                
            order.save()
            pf.append(action.symbol)
            ocap.capital-=1
            ocap.save()
            return True
        return False
    
    except Exception as e:
        logger.error(str(e) + "symbol: "+str(symbol), stack_info=True, exc_info=True)
        pass
   
def check_hold_duration(symbol,strategy, exchange,short,**kwargs): 
        #type check necessary for indexes
    try:
        pf= get_pf(strategy, exchange,short,**kwargs)
        action=Action.objects.get(symbol=symbol)
        action=action_to_etf(action,short)

        #accountSummary
        if action.symbol in pf.retrieve():
            c1 = Q(action=action)
            c2 = Q(active=True)
            order=Order.objects.filter(c1 & c2)
            if len(order)>0:
                delta=timezone.now()-order[0].entering_date
                return delta.days
        
        return 0
    except Exception as e:
         logger.error(e, stack_info=True, exc_info=True)
         return 0

def check_auto_manual(func,symbol,strategy, exchange,short,auto,**kwargs):
    def wrapper(*args,**kwargs):
        try: 
            action=Action.objects.get(symbol=symbol)
            stock_ex=StockEx.objects.get(name=exchange)
            strat=Strategy.objects.get(name=strategy)
        except Exception as e:
            logger.error(e, stack_info=True, exc_info=True)
            logger.error("action: " + str(symbol) + ", stock_ex: "+str(exchange) + ", strat: " + str(strategy) + " not found")
            
        try:

            if (kwargs['client'] and ib_global["connected"] and
               _settings["PERFORM_ORDER"] and
               (not check_if_index(action) or (check_if_index(action) and _settings["ETF_IB_auth"])) and #ETF trading requires too high 
               stock_ex.perform_order and  #ETF trading requires too high permissions on IB, XETRA data too expansive
               strat.perform_order and
               not auto==False):

                auto_checked=True
    
            else: 
                auto_checked=False
            
            return func(symbol,strategy, exchange,short,auto_checked,**kwargs), auto_checked
        except Exception as e:
            
             logger.error(e, stack_info=True, exc_info=True)
             return False, False
    
    return wrapper(symbol,strategy, exchange,short,auto,**kwargs)     
@connect_ib     
def reverse_order(symbol,strategy, exchange,short,auto,**kwargs):
    return check_auto_manual(reverse_order_sub,symbol,strategy, exchange,short,auto,**kwargs)

@connect_ib       
def entry_order(symbol,strategy, exchange,short,auto,**kwargs):
    return check_auto_manual(entry_order_sub,symbol,strategy, exchange,short,auto,**kwargs)

@connect_ib
def exit_order(symbol,strategy, exchange,short,auto,**kwargs): 
    return check_auto_manual(exit_order_sub,symbol,strategy, exchange,short,auto,**kwargs)

def check_if_index(action):
    if action.category==ActionCategory.objects.get(short="IND"):
        return True
    else:
        return False    
 
# All symbols must be from same stock exchange
#IB need a ticker, an exchange and information about the type of product to find the correct contract
@connect_ib 
def retrieve_data_ib(actions,period,**kwargs):
    try:
        period=period_YF_to_ib(period)
        exchanges={}
        indexes={}
        ib_symbols=[]
        
        for a in actions:
            ib_symbol=a.ib_ticker()
            ib_symbols.append(ib_symbol)
            exchanges[ib_symbol]=a.stock_ex.ib_ticker
            indexes[ib_symbol]=kwargs.get("index",False)
        
        #add the index to the list of stocks downloaded. Useful to make calculation on the index to determine trends
        #by downloading at the same time, we are sure the signals are aligned
        if kwargs.get("index",False):
            index_symbol=ib_symbols[0]
            all_symbols=ib_symbols
        else:
            index_symbol_ib, index_symbol=exchange_to_index_symbol(actions[0].stock_ex) 
            all_symbols= ib_symbols+[index_symbol_ib]
            indexes[index_symbol_ib]=True
            action=Action.objects.get(symbol=index_symbol)
            exchanges[index_symbol_ib]=action.stock_ex.ib_ticker    

        ok=False
        
        #test if the symbols were downloaded
        while not ok and len(ib_symbols)>=0:
            res=IBData.fetch(
                all_symbols, 
                period=period,
                missing_index='drop',
                timeframe="1 day", #see also interval_YF_to_ib
                exchanges=exchanges,
                indexes=indexes)
            ok=True
            o=res.get('Open')
            for s in ib_symbols:
                try:
                    o[s]
                except:
                    logger.info("symbol not found: "+s)
                    ok=False
                    ib_symbols.remove(s)
                    all_symbols.remove(s)

        return res,\
            ib_symbols,\
            index_symbol_ib
    except Exception as e:
         logger.error(e, stack_info=True, exc_info=True)
#YF can work with only the symbol to obtain the right contract
def retrieve_data_YF(actions,period,**kwargs):
    #add the index to the list of stocks downloaded. Useful to make calculation on the index to determine trends
    #by downloading at the same time, we are sure the signals are aligned
    try:
        symbols=[a.symbol for a in actions]
        if kwargs.get("index",False):
            index_symbol=symbols[0]
            all_symbols=symbols
        else:
            _, index_symbol=exchange_to_index_symbol(actions[0].stock_ex)  
            all_symbols=symbols+[index_symbol]
            
        #res=vbt.YFData.fetch(all_symbols, period=period,missing_index='drop',**kwargs)
        ok=False
        first_round=True
        #look for anomaly
        if len(all_symbols)>2:
            res=vbt.YFData.fetch(all_symbols, period=period,missing_index='drop',**kwargs)
            avg=np.average(
                [len(vbt.YFData.fetch(all_symbols[0], period=period,**kwargs).get('Open')),
                len(vbt.YFData.fetch(all_symbols[1], period=period,**kwargs).get('Open')),
                len(vbt.YFData.fetch(all_symbols[-1], period=period,**kwargs).get('Open'))]
                )
            
            if len(res.get('Open'))<avg-10:
                print("Anomaly found by downloading the symbols, check that the symbol with most nan is not delisted or if its introduction date is correct")
                
                res_nodrop=vbt.YFData.fetch(all_symbols, period=period,**kwargs)
                nb_nan={}
                for c in res.get('Open').columns:
                    nb_nan[c]=np.count_nonzero(np.isnan(res_nodrop.get('Open')[c]))

                nb_nan=sorted(nb_nan.items(), key=lambda tup: tup[1],reverse=True)
                print("Number of nan in each column: "+str(nb_nan))
        else:
            first_round=False
        
        #test if the symbols were downloaded
        while not ok and len(symbols)>=0:
            if not first_round:
                res=vbt.YFData.fetch(all_symbols, period=period,missing_index='drop',**kwargs)
            ok=True
            o=res.get('Open')
            for s in symbols:
                try:
                    o[s]
                except:
                    logger.info("symbol not found: "+s)
                    ok=False
                    symbols.remove(s)
                    all_symbols.remove(s)
        
        return res,\
               symbols,\
               index_symbol    
    except Exception as e:
         print(e)
         logger.error(e, stack_info=True, exc_info=True)
        
def retrieve_data(o,actions,period,use_IB,**kwargs):
    if actions is None or len(actions)==0:
        raise ValueError("List of symbols empty, is there any stocks related to the requested stock exchange?")
    else:
        if use_IB:
            try:
                cours, symbols, index_symbol=retrieve_data_ib(actions,period,**kwargs)
            except:
                logger.info("IB retrieval of symbol failed, fallback on YF")
                use_IB=False #fallback
        if not use_IB:
            cours, symbols, index_symbol=retrieve_data_YF(actions,period,**kwargs)

        o.data=cours.select(symbols)
        o.data_ind=cours.select(index_symbol)
        
        for l in ["Close","Open","High","Low","Volume"]:
            setattr(o,l.lower(),o.data.get(l))
            setattr(o,l.lower()+"_ind",o.data_ind.get(l))
            
        logger.info("number of days retrieved: " + str(np.shape(o.close)[0]))
        if len(o.open_ind)==0 or len(o.open_ind)==0:
            raise ValueError("Retrieve data failed and returned empty Dataframe, check the symbols")

        return use_IB, symbols
               
               
               