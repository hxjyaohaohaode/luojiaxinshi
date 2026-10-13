"""Server/client consistency and hostile-input tests; no provider or credentials."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from app.genui import Block, LIMITS, parse_message, safe_value, validate_expression, validate_node

ROOT = Path(__file__).resolve().parent.parent


def wrap(ops):
    return '前文中文🌸\n```genui\n'+'\n'.join(json.dumps(o,ensure_ascii=False) if not isinstance(o,str) else o for o in ops)+'\n```\n后文'


BEGIN={'op':'begin','v':1}
END={'op':'end'}


def test_client_server_canonical_specs_agree():
    node=shutil.which('node')
    assert node, 'Node is required for cross-runtime protocol verification'
    texts=[(ROOT/'fixtures/genui/study-plan.md').read_text(encoding='utf-8'), '文本\u2028仍在同一行\n', wrap([BEGIN,{'op':'state','set':{'hours':2}},
        {'op':'node','id':'x','type':'Stat','props':{'label':'结果','value':{'$expr':'round(hours*7,1)'}}},
        {'op':'node','id':'bad','type':'Slider','props':{'label':'bad','bind':'hours','style':'color:red'}},'bad JSON',END]),
        wrap([BEGIN,{'op':'node','id':'a','type':'Stack','children':['b']},{'op':'node','id':'b','type':'Stack','children':['a','lost']},END]),
        wrap([BEGIN,{'op':'node','id':'x','type':'NoSuchType'},END]),
        '```genui\n'+json.dumps(BEGIN)+'\n'+json.dumps({'op':'node','id':'x','type':'Markdown','props':{'text':'部分回答'}})+'\n']
    script="import {parseMessage} from './static/genui/core.js';let raw='';for await(const chunk of process.stdin)raw+=chunk;process.stdout.write(JSON.stringify(JSON.parse(raw).map(t=>parseMessage(t))));"
    run=subprocess.run([node,'--input-type=module','-e',script],cwd=ROOT,input=json.dumps(texts),encoding='utf-8',capture_output=True,check=True)
    assert json.loads(run.stdout)==[parse_message(text) for text in texts]


@pytest.mark.parametrize('value',[{'constructor':{}},{'a':[{'__proto__':'x'}]},{'prototype':1},float('inf'),{'a':'中'*3000}])
def test_unsafe_values_rejected(value):
    with pytest.raises(ValueError):safe_value(value)


@pytest.mark.parametrize('source',['eval("x")','x.constructor','x[0]','x=1','while(true)','window.alert(1)','1;2','('.join(['1']*300)])
def test_expression_syntax_cannot_address_executable_objects(source):
    with pytest.raises(ValueError):validate_expression(source)


def test_accepted_expressions_and_limits():
    for source in ['round(principal*pow(1+rate/100,years),0)','a > 2 ? max(a,3) : 0','false && missing.path','sum(items)']:
        validate_expression(source)
    with pytest.raises(ValueError):validate_expression('1+'*251+'1')
    b=Block({**LIMITS,'stateKeys':1});b.apply(BEGIN);b.apply({'op':'state','set':{'a':1}});b.apply({'op':'state','set':{'b':2}})
    assert b.state=={'a':1}
    for i in range(301):b.apply({'op':'node','id':'n'+str(i),'type':'Markdown','props':{'text':'x'}})
    assert len(b.nodes)==300
    assert any(e['code']=='node_limit' for e in b.errors)


def test_forged_data_and_node_fields_are_rejected():
    b=Block();b.apply(BEGIN);b.apply({'op':'data','id':'grades','value':[100]});assert b.data=={}
    b.apply({'op':'data','id':'grades','value':[85]},trusted=True);assert b.data=={'grades':[85]}
    for prop in ['style','html','srcdoc','onclick']:
        with pytest.raises(ValueError):validate_node({'id':'x','type':'Markdown','props':{prop:'javascript:evil'}})


def test_generated_catalog_has_no_drift():
    run=subprocess.run([__import__('sys').executable,'scripts/genui_catalog.py','--check'],cwd=ROOT,capture_output=True,text=True)
    assert run.returncode==0,run.stdout+run.stderr
