const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const inline=value=>escape(value).replace(/`([^`\n]+)`/g,'<code>$1</code>').replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>');

// Text only: no HTML execution, external images or generated action links.
export function formatAnswer(value){
  const blocks=String(value).split(/\n/),out=[];let list=null,code=false,codeLines=[];
  const closeList=()=>{if(list){out.push('</'+list+'>');list=null;}};
  for(const line of blocks){
    if(/^\s*```/.test(line)){closeList();if(code){out.push('<pre><code>'+escape(codeLines.join('\n'))+'</code></pre>');codeLines=[];}code=!code;continue;}
    if(code){codeLines.push(line);continue;}
    const bullet=line.match(/^\s*[-*•]\s+(.+)$/),number=line.match(/^\s*\d+[.、)]\s+(.+)$/),heading=line.match(/^#{1,4}\s+(.+)$/);
    if(bullet||number){const type=bullet?'ul':'ol';if(list!==type){closeList();list=type;out.push('<'+type+'>');}out.push('<li>'+inline((bullet||number)[1])+'</li>');}
    else{closeList();if(heading)out.push('<h3>'+inline(heading[1])+'</h3>');else if(line.trim())out.push('<p>'+inline(line)+'</p>');}
  }
  closeList();if(codeLines.length)out.push('<pre><code>'+escape(codeLines.join('\n'))+'</code></pre>');return out.join('');
}
