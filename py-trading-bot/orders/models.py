from django.db import models
from django.db.models import Q

from trading_bot.settings import _settings
import datetime
#from orders.ib import 
import logging
logger = logging.getLogger(__name__)

import sys
if sys.version_info.minor>=9:
    import zoneinfo
    from zoneinfo import ZoneInfo
else:
    import backports.zoneinfo as zoneinfo
    from backports.zoneinfo import ZoneInfo
    
tz_Paris=ZoneInfo('Europe/Paris')

all_tz=[]
for tz in zoneinfo.available_timezones():
    all_tz.append((tz,tz))
all_tz=sorted(all_tz)  

### Check if IB can be used
def check_ib_permission(symbols):
    IBok=True
    for symbol in symbols:
        if symbol in _settings["IB_STOCK_NO_PERMISSION"]:
            logger.info("symbol " + symbol + " has no permission for IB")
            IBok=False
            break
        
        a=Action.objects.get(symbol=symbol)      
        if a.stock_ex.ib_auth==False:
            logger.info("stock ex " + a.stock_ex.ib_ticker + " has no permission for IB")
            IBok=False
            break
    
    return IBok
    
### Get lists of actions for the reporting
def get_exchange_actions(exchange,**kwargs):
    cat=ActionCategory.objects.get(short="ACT")
    
    try:
        stock_ex=StockEx.objects.get(name=exchange)
    except:
        raise ValueError("Stock exchange: "+str(exchange)+" not found, create it in the admin panel")
    
    c1 = Q(category=cat)
    c2 = Q(stock_ex=stock_ex)
    c3 = Q(delisted=False) #to be removed
    
    if stock_ex.presel_at_sector_level and kwargs.get("sec"):
        action_sector, _=ActionSector.objects.get_or_create(name=kwargs.get("sec"))
        c4 = Q(sector=action_sector)
        actions=Action.objects.filter(c1 & c3 & c4) #c2 & no actual reason, but I use mix of Nasdaq and NYSE for sector
    else:
        actions=Action.objects.filter(c1 & c2 & c3)
        
    if len(actions)==0: #fallback for EUREX for instance
        cat=ActionCategory.objects.get(short="IND")
        c1 = Q(category=cat)
        actions=Action.objects.filter(c1 & c2 & c3)

    #actions=filter_intro_action( actions,None)  
    use_IB=False
    if _settings["USE_IB_FOR_DATA"]["reporting"]:
        use_IB=check_ib_permission([a.symbol for a in actions])

    return use_IB, actions

### Conversion between input from YF and IB
def period_YF_to_ib(period): #see also split_freq_str in vbt
    #transform "10 d" in "10 D"
    period_ib=None
    if period is not None:
        fig= ''.join(x for x in period if x.isdigit())
        if period.find("d")!=-1:
            period_ib=fig +" D"
        elif period.find("mo")!=-1:
            period_ib=fig +" M"
        elif period.find("y")!=-1:
            period_ib=fig +" Y"  
    
    return period_ib

def interval_YF_to_ib(interval):
    #Time period of one bar. Must be one of: ‘1 secs’, ‘5 secs’, ‘10 secs’ 15 secs’, ‘30 secs’, ‘1 min’, ‘2 mins’, ‘3 mins’, ‘5 mins’, ‘10 mins’, ‘15 mins’, ‘20 mins’, ‘30 mins’, ‘1 hour’, ‘2 hours’, ‘3 hours’, ‘4 hours’, ‘8 hours’, ‘1 day’, ‘1 week’, ‘1 month’.
    if interval is None:
        res='1 day'
    else:
        fig= ''.join(x for x in interval if x.isdigit())
        if interval.find("m")!=-1:
            res=fig +" mins"
        elif interval.find("h")!=-1:
            res=fig +" hours"
        elif interval.find("d")!=-1:
            res=fig +" day"
        else:
            res='1 day'
            
    return res

### Data retrieval ###
def exchange_to_index_symbol(exchange):
    if type(exchange)==str:
        stock_ex=StockEx.objects.get(name=exchange)
    elif type(exchange)==StockEx:
        stock_ex=exchange
    else:
        raise ValueError("exchange has the wrong type")
    
    if stock_ex.main_index is None:
        return ["COMP","^IXIC"]
    else:
        return [stock_ex.main_index.ib_ticker(),stock_ex.main_index.symbol]
    
def action_to_etf(action,short):
    if action.category==ActionCategory.objects.get(short="IND"):
        if short:
            return action.etf_short
        else:
            return action.etf_long
    return action

def symbol_to_action(symbol):
    if type(symbol)==str:
        return Action.objects.get(symbol=symbol)
    else:
        return symbol #action in this case

class Currency(models.Model):
    name=models.CharField(max_length=100, blank=False)
    symbol=models.CharField(max_length=100, blank=False,default="A")
    
    class Meta:
        ordering = ["name"]
        
    def __str__(self):
        return self.name
    
class Fees(models.Model):
    name=models.CharField(max_length=100, blank=False, default="fee")
    fixed=models.DecimalField(max_digits=100, decimal_places=5)
    percent=models.DecimalField(max_digits=100, decimal_places=5)
    
    def __str__(self):
        return self.name  

class Strategy(models.Model):
    name=models.CharField(max_length=100, blank=False)
    perform_order=models.BooleanField(blank=False,default=False)
    
    class Meta:
        ordering = ["name"]
        
    def __str__(self):
        return self.name
    
class StockEx(models.Model):
    name=models.CharField(max_length=100, blank=False)
    fees=models.ForeignKey('Fees',on_delete=models.CASCADE)
    ib_ticker=models.CharField(max_length=15, blank=True,default="AAA")
    opening_time=models.TimeField(default=datetime.time(9, 00))
    closing_time=models.TimeField(default=datetime.time(17, 00))
    timezone=models.CharField(max_length=60,choices=all_tz, blank=False,default='Europe/Paris')
    perform_order=models.BooleanField(blank=False,default=False)
    ib_auth=models.BooleanField(blank=False,default=False)
    strategies_in_use=models.ManyToManyField(Strategy,blank=True)   # Presel strategies in use, normal/sl/tsl depends on the selected candidates
    presel_at_sector_level=models.BooleanField(blank=False,default=False)
    main_index=models.ForeignKey('Action',on_delete=models.CASCADE,blank=True,null=True,default=None)
    
    class Meta:
        ordering = ["name"]
    
    def __str__(self):
        return self.name 
    
### Index is like stock (but it had to be separated, as an index cannot be bought directly
class Action(models.Model): #Action means stock in French
    symbol=models.CharField(max_length=15, blank=False, primary_key=True)
    ib_ticker_explicit=models.CharField(max_length=15, blank=True,default="AAA") #for index especially
    name=models.CharField(max_length=100, blank=False)
    stock_ex=models.ForeignKey('StockEx',on_delete=models.CASCADE)
    currency=models.ForeignKey('Currency',on_delete=models.CASCADE)
    category=models.ForeignKey('ActionCategory',on_delete=models.CASCADE,blank=True)
    sector=models.ForeignKey('ActionSector',on_delete=models.CASCADE,blank=True,default=None)
    delisted=models.BooleanField(blank=False,default=False)
    etf_long=models.ForeignKey('self',on_delete=models.CASCADE,related_name='etf_long2',blank=True,null=True)
    etf_short=models.ForeignKey('self',on_delete=models.CASCADE,related_name='etf_short2',blank=True,null=True)
    
    intro_date=models.DateTimeField(null=True, blank=True, default=None)
    delisting_date=models.DateTimeField(null=True, blank=True, default=None)
    
    class Meta:
        ordering = ["name"]
        
    def ib_ticker(self):
        if self.ib_ticker_explicit!="AAA" and self.ib_ticker_explicit is not None:
            return self.ib_ticker_explicit
        else:
            t=self.symbol.split(".")
            return t[0]      
        
    def __str__(self):
        return self.name
    
def filter_intro_sub(a,y_period):
    td=datetime.datetime.today()
    if y_period is None:
        limit_date=td
    else:
        limit_date=datetime.datetime(td.year-y_period,td.month,td.day,tzinfo=tz_Paris) #time zone not important here but otherwise bug

    if a.intro_date is not None: #should come from database
        if a.intro_date>limit_date :
           return False
    if a.delisting_date is not None:
        if a.delisting_date<limit_date :
           return False
    return True

def filter_intro_action(input_actions,y_period):
    actions=[]
    for a in input_actions:
        if filter_intro_sub(a,y_period):
            actions.append(a)   
    return actions

class Order(models.Model):
    action=models.ForeignKey('Action',on_delete=models.CASCADE)
    pf=models.ForeignKey('PF',on_delete=models.SET_NULL,blank=True,null=True)
    active=models.BooleanField(blank=False,default=True)
    short=models.BooleanField(blank=False,default=False)
    entering_date=models.DateTimeField(null=False, blank=False, auto_now_add=True)#default=timezone.now())
    exiting_date=models.DateTimeField(null=True, blank=True)
    entering_price=models.DecimalField(max_digits=100, decimal_places=5,blank=True,null=True)
    exiting_price=models.DecimalField(max_digits=100, decimal_places=5,blank=True,null=True)
    sl_threshold=models.DecimalField(max_digits=100, decimal_places=5,blank=True,null=True) #as price
    daily_sl_threshold=models.DecimalField(max_digits=100, decimal_places=5,blank=True,null=True) #as pu
    profit=models.DecimalField(max_digits=100, decimal_places=5,blank=True,null=True)
    profit_percent=models.DecimalField(max_digits=100, decimal_places=5,blank=True,null=True)
    quantity=models.DecimalField(max_digits=100, decimal_places=5,blank=True,null=True)
    
    def __str__(self):
        return self.action.name + " "+ str(self.entering_date)

def pf_retrieve_all(**kwargs):
    a=[]
    for pf in PF.objects.filter(short=kwargs.get("short",False)):
        if kwargs.get("opening")=="9h":
            stockEx1=StockEx.objects.filter(name="Paris")
            stockEx2=StockEx.objects.filter(name="XETRA")
            c2 = Q(stock_ex=stockEx1[0])
            c3 = Q(stock_ex=stockEx2[0])
            actions=pf.actions.filter((c2|c3))#c1 &
        elif kwargs.get("opening")=="15h":
            stockEx1=StockEx.objects.filter(name="Nasdaq")
            stockEx2=StockEx.objects.filter(name="NYSE")
            c2 = Q(stock_ex=stockEx1[0])
            c3 = Q(stock_ex=stockEx2[0])
            actions=pf.actions.filter( (c2|c3)) #c1 &
        else:
            actions=pf.actions.all() #filter(c1)
        a+=actions

    return list(set(a)) #unique

### Portfolio for a given strategy (used as name presently)
class PF(models.Model):
    # can be replaced with ib.positions() or ib.portfolio()
    actions=models.ManyToManyField(Action,blank=True)
    sector=models.ForeignKey('ActionSector',on_delete=models.CASCADE,blank=True,default=0)
    short=models.BooleanField(blank=False,default=False)
    strategy=models.ForeignKey('Strategy',on_delete=models.CASCADE,blank=True)
    stock_ex=models.ForeignKey('StockEx',on_delete=models.CASCADE,blank=True,default=0)
    
    class Meta:
        ordering = ["strategy","stock_ex"]
    
    def get_len(self):
        return len(self.actions.all())
    
    def retrieve(self):
        return [action.symbol for action in self.actions.all()]

    def remove(self,symbol):
        try:
            a=symbol_to_action(symbol)
            self.actions.remove(a)
            self.save()
        except Exception as e:
            logger.error(e + " symbol: " + symbol, stack_info=True, exc_info=True)          
            pass

    def append(self,symbol):
        try:
            if type(symbol)==str:
                a = Action.objects.get(symbol=symbol)
            else: #assumed action
                a=symbol
            self.actions.add(a)
            self.save()
        except Exception as e:
            logger.error(e + " symbol: "+symbol, stack_info=True, exc_info=True)
            pass
        
    def __str__(self):
        t=self.strategy.name + "_" + self.stock_ex.name
        if self.short:
            t+="_short"
        if self.sector.name!="undefined":
            t+=("_" +self.sector.name)
        return t

def get_sub(strategy, exchange,short,**kwargs): #check the input
    if type(strategy)!=str or type(exchange)!=str:
        raise ValueError("get sub got non str input, strategy: "+str(strategy)+ " "+str(type(strategy)) + \
                         ", exchange: "+str(exchange) + " " + str(type(exchange)))

    try:
        stock_ex=StockEx.objects.get(name=exchange) 
    except:
        raise ValueError("Stock exchange: "+str(exchange)+" not found, create it in the admin panel")

    sector="undefined"
    if stock_ex.presel_at_sector_level:
        if kwargs.get("sec"):
            sector=kwargs.get("sec")
            
    return sector

def get_pf(strategy, exchange,short,**kwargs):
    try:
        sector=get_sub(strategy, exchange,short,**kwargs)
        res, _ = PF.objects.get_or_create(
                stock_ex=StockEx.objects.get(name=exchange),
                strategy=Strategy.objects.get(name=strategy),
                short=short,
                sector=ActionSector.objects.get(name=sector),
                )

        return res
    except Exception as e:
        logger.error(strategy)
        logger.error(e, stack_info=True, exc_info=True)

### To distinguish between ETF, actions, indexes...
class ActionCategory(models.Model):
    short=models.CharField(max_length=15, blank=False, default="AAA", primary_key=True)
    name=models.CharField(max_length=100, blank=False)
        
    def __str__(self):
        return self.name 

###GICS sectors    
class ActionSector(models.Model):
    name=models.CharField(max_length=100, blank=False)
    strategies_in_use=models.ManyToManyField(Strategy,blank=True)   
    
    class Meta:
        ordering = ["name"]
        
    def __str__(self):
        return self.name     
    
###To define the number of orders assigned to one strategy
###1 means that only one action can be owned at a time using this strategy

class OrderCapital(models.Model):
    capital=models.DecimalField(max_digits=100, decimal_places=5,blank=True,null=True)
    strategy=models.ForeignKey('Strategy',on_delete=models.CASCADE,blank=True)
    stock_ex=models.ForeignKey('StockEx',on_delete=models.CASCADE,blank=True,default=2)
    sector=models.ForeignKey('ActionSector',on_delete=models.CASCADE,blank=True,default=0)

    class Meta:
        ordering = ["strategy","stock_ex"]
        
    def __str__(self):
        t=self.strategy.name + "_" + self.stock_ex.name
        if self.sector.name!="undefined":
            t+=("_" +self.sector.name)
        return t

def get_order_capital(strategy, exchange,**kwargs):
    try:
        sector=get_sub(strategy, exchange,False,**kwargs)
        res, created = OrderCapital.objects.get_or_create(
            stock_ex=StockEx.objects.get(name=exchange),
            strategy=Strategy.objects.get(name=strategy),
            sector=ActionSector.objects.get(name=sector),
            )
        
        if created or res.capital is None:
            res.capital=0
        
        return res
    except Exception as e:
        logger.error(e, stack_info=True, exc_info=True)           

###For strategy using two time frame, in the slow one (10 days) candidates are defined
###And on daily basis the other strategy decides which of the candidate is really bought or sold

class Candidates(models.Model):
    actions=models.ManyToManyField(Action,blank=True)    
    strategy=models.ForeignKey('Strategy',on_delete=models.CASCADE,blank=True,default=1)
    stock_ex=models.ForeignKey('StockEx',on_delete=models.CASCADE,blank=True,default=2)
    
    def reset(self):
        for a in self.actions.all():
            self.actions.remove(a)
            self.save()
    
    def append(self,symbol): #so we can name as for list
        a=symbol_to_action(symbol)
        self.actions.add(a)
        self.save()
        
    def retrieve(self):
        return [action.symbol for action in self.actions.all()]
    
    def __str__(self):
        return self.strategy.name + "_" + self.stock_ex.name

def get_candidates(strategy, exchange):
    res, _ = Candidates.objects.get_or_create(
        stock_ex=StockEx.objects.get(name=exchange),
        strategy=Strategy.objects.get(name=strategy),
        )
    return res
    
### List of actions provisory excluded for a strategy as it risks to perform bad
    
class Excluded(models.Model):
    name=models.CharField(max_length=100, blank=False)
    actions=models.ManyToManyField(Action,blank=True)   
    strategy=models.ForeignKey('Strategy',on_delete=models.CASCADE,blank=True)
    
    def reset(self):
        for a in self.actions.all():
            self.actions.remove(a)
            self.save()
    
    def append(self,symbol):
        a=symbol_to_action(symbol)
        self.actions.add(a)
        self.save()
        
    def remove(self,symbol):
        try:
            a=symbol_to_action(symbol)
            self.actions.remove(a)
            self.save()
        except Exception as e:
            logger.error(e + " symbol: "+symbol, stack_info=True, exc_info=True)    
            pass
        
    def retrieve(self):
        return [action.symbol for action in self.actions.all()]
    
    def __str__(self):
        return self.name 
 
### Define a list of actions and indexes that can be traded using the defined strategy
class StratCandidates(models.Model):
    actions=models.ManyToManyField(Action,blank=True)    
    strategy=models.ForeignKey('Strategy',on_delete=models.CASCADE,blank=True,default=0)
    
    def retrieve(self):
        return [action.symbol for action in self.actions.all()]
    
    def __str__(self):
        return self.strategy.name   
    
class Job(models.Model):
    strategy=models.ForeignKey('Strategy',on_delete=models.CASCADE,blank=True,default=0)
    stock_ex=models.ForeignKey('StockEx',on_delete=models.CASCADE,blank=True,default=2)
    
    last_execution=models.DateTimeField(null=False, blank=False, auto_now_add=True)
    frequency_days=models.IntegerField(null=False, blank=False, default=14)
    period_year=models.IntegerField(null=False, blank=False, default=1)
    
    def __str__(self):
        return self.strategy.name + "_" + self.stock_ex.name