// Feedback is a separate read projection. It does not invalidate a model run
// or overwrite unsaved controls in an interactive answer.
export class ChatFeedback{
  constructor(){this.values=new Map();this.epoch=0;this.signature=null;}
  reset(chat){this.values.clear();this.epoch++;this.signature=null;for(const message of chat?.messages||[])for(const item of [message,...(message.versions||[])])if(!this.values.has(item.id))this.values.set(item.id,{emojis:item.emojis||[],reaction:item.reaction||0});}
  patch(message,values){this.values.set(message.id,{emojis:message.emojis||[],reaction:message.reaction||0,...values});this.epoch++;this.signature=null;this.applyMessage(message);}
  applyMessage(message){const value=this.values.get(message.id);if(value)Object.assign(message,{emojis:[...value.emojis],reaction:value.reaction});for(const version of message.versions||[])if(version!==message)this.applyMessage(version);}
  apply(chat){for(const message of chat?.messages||[])this.applyMessage(message);return chat;}
  accept(chat,data,epoch){if(epoch!==this.epoch||data.signature===this.signature)return false;this.signature=data.signature;
    const messages=(chat?.messages||[]).flatMap(message=>[message,...(message.versions||[])]);
    this.values.clear();for(const message of messages)this.values.set(message.id,{emojis:data.emojis[message.id]||[],reaction:data.reactions[message.id]||0});
    this.apply(chat);return true;
  }
}
