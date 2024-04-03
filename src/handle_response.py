from bs4 import BeautifulSoup
import time
class ResponseHandler:
    def __init__(self):
        pass 
    def extract_response_text(self,response):
        if not response:
            raise Exception("Tried to extract None Response -- Response Object is None")
        
        response_text = response.text
        result = ' '.join(BeautifulSoup(response_text, "html.parser").stripped_strings)
        #assume the response_text is html since that is the worst case scenario
        return result
    def classify_error(self, response):
        response_text = self.extract_response_text(response)
        #TODO: classify the error 
    def handle_error(self):
        pass 
        #TODO:handle the error
    
    

class DummyResponse:
    def __init__(self, type="html"):
        if type == "html":
            self.text = '''
            <!doctype html><html lang="en"><head><script async src="https://www.googletagmanager.com/gtag/js?id=UA-17134933-4"></script><script src="https://kit.fontawesome.com/6be4547409.js" crossorigin="anonymous"></script><script>function gtag(){dataLayer.push(arguments)}window.dataLayer=window.dataLayer||[],gtag("js",new Date),gtag("config","UA-17134933-4")</script><meta charset="utf-8"/><link rel="icon" href="/favicon.ico"/><meta name="viewport" content="width=device-width,initial-scale=1"/><meta name="theme-color" content="#000000"/><link rel="manifest" href="/manifest.json"/><title>Genome Nexus</title><link href="/static/css/2.e87a3ba9.chunk.css" rel="stylesheet"><link href="/static/css/main.276d8240.chunk.css" rel="stylesheet"></head><body><noscript>You need to enable JavaScript to run this app.</noscript><div id="root"></div><script>!function(e){function r(r){for(var n,f,l=r[0],i=r[1],a=r[2],c=0,s=[];c<l.length;c++)f=l[c],Object.prototype.hasOwnProperty.call(o,f)&&o[f]&&s.push(o[f][0]),o[f]=0;for(n in i)Object.prototype.hasOwnProperty.call(i,n)&&(e[n]=i[n]);for(p&&p(r);s.length;)s.shift()();return u.push.apply(u,a||[]),t()}function t(){for(var e,r=0;r<u.length;r++){for(var t=u[r],n=!0,l=1;l<t.length;l++){var i=t[l];0!==o[i]&&(n=!1)}n&&(u.splice(r--,1),e=f(f.s=t[0]))}return e}var n={},o={1:0},u=[];function f(r){if(n[r])return n[r].exports;var t=n[r]={i:r,l:!1,exports:{}};return e[r].call(t.exports,t,t.exports,f),t.l=!0,t.exports}f.m=e,f.c=n,f.d=function(e,r,t){f.o(e,r)||Object.defineProperty(e,r,{enumerable:!0,get:t})},f.r=function(e){"undefined"!=typeof Symbol&&Symbol.toStringTag&&Object.defineProperty(e,Symbol.toStringTag,{value:"Module"}),Object.defineProperty(e,"__esModule",{value:!0})},f.t=function(e,r){if(1&r&&(e=f(e)),8&r)return e;if(4&r&&"object"==typeof e&&e&&e.__esModule)return e;var t=Object.create(null);if(f.r(t),Object.defineProperty(t,"default",{enumerable:!0,value:e}),2&r&&"string"!=typeof e)for(var n in e)f.d(t,n,function(r){return e[r]}.bind(null,n));return t},f.n=function(e){var r=e&&e.__esModule?function(){return e.default}:function(){return e};return f.d(r,"a",r),r},f.o=function(e,r){return Object.prototype.hasOwnProperty.call(e,r)},f.p="/";var l=this["webpackJsonpgenome-nexus-frontend"]=this["webpackJsonpgenome-nexus-frontend"]||[],i=l.push.bind(l);l.push=r,l=l.slice();for(var a=0;a<l.length;a++)r(l[a]);var p=i;t()}([])</script><script src="/static/js/2.3efbd946.chunk.js"></script><script src="/static/js/main.92aaf9d8.chunk.js"></script></body></html>
            '''.strip()
        if type == "json":
            self.text = '''
            {"variant":"cjgQ3mGPnuaXGKU","originalVariantQuery":"cjgQ3mGPnuaXGKU","successfully_annotated":false}
            '''.strip()
        if type == "plaintext":
            self.text = '''
            successful            
            '''.strip()

        
if __name__ == '__main__':
    start_time = time.time()
    response_handler = ResponseHandler() 
    print(response_handler.extract_response_text(DummyResponse(type="html")))
    end_time = time.time() 
    print(f"elapsed extraction time {end_time - start_time}")
