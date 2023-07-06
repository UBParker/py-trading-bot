from django.shortcuts import render
from orders.models import Order, StratCandidates
from orders.form import ManualOrderForm
from django.db.models import Q
from django.http import HttpResponse
# Create your views here.
'''
def pf_view(request):
    form=ManualOrderForm(request.POST or None)
    
    if request.method == 'POST':
        if form.is_valid():
            action=form.cleaned_data["action"]
            c1=Q(strategy=form.cleaned_data["strategy"])
            c2=Q(stock_ex=action.stock_ex)
            c3=Q(short=form.cleaned_data["short"])  
            c4=Q(sector=form.cleaned_data["sector"])
            c5 =Q(action=action)
            c6= Q(active=True)
            
            pfs=PF.objects.filter(c1&c2&c3&c4)
            #optional
            try:
                oc=OrderCapital.objects.get(c1 & c2 & c4)
            except:
                oc=None
                pass
            
            if len(pfs)==0:
                return HttpResponse("Corresponding pf not found")
            elif len(pfs)>1:
                return HttpResponse("Several corresponding pf found, do the step manually in the admin panel")
            else:
                pf=pfs[0]
            c7= Q(pf=pf)
            
            if "closing" in request.POST:
                closing(action,pf, c3, c5, c6, c7, oc)
            elif "opening" in request.POST:    
                opening(form, action, pf, oc, None)
            elif "reverse" in request.POST:
                o=closing(action,pf, c3, c5, c6, c7, oc)
                o.short=not o.short
                o.save()
                c3_inv=Q(short=o.short)  
                pfs_inv=PF.objects.filter(c1&c2&c3_inv&c4)
                
                if len(pfs_inv)==0:
                    return HttpResponse("Corresponding pf inv not found")
                elif len(pfs_inv)>1:
                    return HttpResponse("Several corresponding pf inv found, do the step manually in the admin panel")
                else:
                    pf_inv=pfs_inv[0]
                    
                pf_inv.append(action.symbol) 
                
                if oc is not None:
                    oc.capital-=1
                    oc.save()
                    
                sc=StratCandidates.objects.filter(strategy=form.cleaned_data["strategy"]) #keep consistency
                if len(sc)>0:
                    if action not in sc[0].actions.all():
                        sc[0].actions.add(action)    
                
    else:
        form = ManualOrderForm(initial={'sl_threshold': 0, "daily_sl_threshold":0, "short":False})
    
    context={'pfs':PF.objects.all(),"form":form}            
    
    return render(request, 'orders/pf.html', context)

def opening(form, action, pf, oc, o):
    if o is None:
        o=Order.objects.create(short=form.cleaned_data["short"], action=action, pf=pf)
    if (form.cleaned_data["sl_threshold"] is not None and form.cleaned_data["sl_threshold"]!=0):
        o.sl_threshold=form.cleaned_data["sl_threshold"]
        o.save()
    
    if (form.cleaned_data["daily_sl_threshold"] is not None and form.cleaned_data["daily_sl_threshold"]!=0):
        print(form.cleaned_data["daily_sl_threshold"])
        o.daily_sl_threshold=form.cleaned_data["daily_sl_threshold"]
        o.save()
    pf.append(action.symbol) 
    
    if oc is not None:
        oc.capital-=1
        oc.save()
    
    sc=StratCandidates.objects.filter(strategy=form.cleaned_data["strategy"]) #keep consistency
    if len(sc)>0:
        if action not in sc[0].actions.all():
            sc[0].actions.add(action)    
 
    
def closing(action,pf, c3, c5, c6, c7, oc):
    orders=Order.objects.filter(c3 & c5 & c6 & c7)
    if len(orders)==0:
        raise ValueError("Order not found")
    elif len(orders)>1:
        raise ValueError("Several orders found, do the step manually in the admin panel")
    else:
        o=orders[0]
    
    if oc is not None:
        oc.capital+=1
        oc.save()
    
    pf.remove(action.symbol) 
    o.active=False
    o.save()
    return o
'''