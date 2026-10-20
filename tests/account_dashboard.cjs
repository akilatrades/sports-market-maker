const assert = require('node:assert/strict');
const view = require('../dashboard/account.js');
const nodes = {};
const document = {getElementById:id => nodes[id] ||= {textContent:'',innerHTML:'',className:'',hidden:false}};
const now = Date.now();
view.render({status:'unavailable'},document,now);
assert.equal(nodes.cash.textContent,'—');
assert.equal(nodes.profit.textContent,'—');
assert.equal(nodes['nba-profit'].textContent,'—');
assert.equal(nodes['budget-bar'].hidden,true);
assert.equal(view.money(null),'—');
assert.equal(view.money(0),'$0.00');
const data = {live_pnl:{nfl:{status:'verified',settled_profit_dollars:1.99,settled_markets:2},nba:{status:'awaiting_first_order',settled_profit_dollars:null,settled_markets:0}},status:'ok',updated_utc:new Date(now).toISOString(),account:{cash_dollars:100,position_value_dollars:2.64,equity_dollars:102.64},strategy:{settled_markets:0,settled_profit_dollars:null,filled_orders:1,contracts_filled:4},positions:[{player:'<img src=x onerror=alert(1)>',ticker:'x',side:'NO',contracts:4,cost_dollars:2.64}],orders:[]};
view.render(data,document,now);
assert.equal(nodes.cash.textContent,'$100.00');
assert.equal(nodes.profit.textContent,'$1.99');
assert.equal(nodes['nba-profit'].textContent,'—');
assert.equal(nodes['settled-note'].textContent,'2 verified settled markets · net of fees');
assert.equal(nodes['nba-settled-note'].textContent,'No live orders accepted yet');
assert.equal(nodes.filled.textContent,'1');
assert.equal(nodes.contracts.textContent,'4');
assert(!nodes['positions-body'].innerHTML.includes('<img'));
assert(nodes['positions-body'].innerHTML.includes('&lt;img'));
assert.equal(view.freshness(data,now+181000),'stale');
view.render({...data,status:'error'},document,now);
assert.equal(nodes.cash.textContent,'$100.00');
assert(nodes.notice.textContent.includes('last successful snapshot'));
assert.equal(nodes.profit.textContent,'—');
assert.equal(nodes['nba-profit'].textContent,'—');
assert.equal(nodes.profit.className,'');
assert.equal(view.freshness({...data,updated_utc:new Date(now+3600000).toISOString()},now),'stale');
view.render({...data,strategy:{...data.strategy,name:'NBA passive NO entries'},orders:[{owned:true,player:'NBA player',contracts:2,price_dollars:0.6}]},document,now);
assert(nodes['orders-list'].innerHTML.includes('NBA passive NO entries'));
assert(!nodes['orders-list'].innerHTML.includes('NFL'));
console.log('Account view: missing values, partial fills, XSS and stale snapshots passed');

const tradeData = {...data,order_audit:{
  nfl:{status:"verified_snapshot",confirmed_unfilled:1,unknown_or_unreconciled:0,accepted_orders:2,orders:[
    {sport:"nfl",player:"Test Player",ticker:"TEST",state:"fully_filled",
     submitted_utc:new Date(now).toISOString(),first_fill_utc:new Date(now).toISOString(),
     filled_contracts:4,ordered_contracts:4,vwap_no_price_dollars:0.61,
     fill_fees_dollars:0.03,maker_filled_contracts:4,exchange_status:"executed"},
    {sport:"nfl",player:"<script>alert(1)</script>",ticker:"BAD",state:"confirmed_unfilled",
     submitted_utc:new Date(now-1000).toISOString(),filled_contracts:0,ordered_contracts:4,
     exchange_status:"canceled"}
  ]},
  nba:{status:"verified_snapshot",accepted_orders:0,confirmed_unfilled:0,unknown_or_unreconciled:0,orders:[]}
}};
view.render(tradeData,document,now);
assert(nodes['unfilled-body'].innerHTML.includes('Filled completely'));
assert(nodes['unfilled-body'].innerHTML.includes('$0.61'));
assert(nodes['unfilled-body'].innerHTML.includes('$0.03'));
assert(nodes['unfilled-body'].innerHTML.includes('Closed · 0 fills'));
assert(!nodes['unfilled-body'].innerHTML.includes('<script>'));
