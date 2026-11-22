const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

class DetailBox {
  constructor() {
    this.children = [];
    this.writes = 0;
  }
  set innerHTML(value) {
    this.html = value;
    this.writes += 1;
    this.children = [value];
  }
  querySelectorAll() { return []; }
}

class PageDocument {
  constructor(box, back) {
    this.box = box;
    this.back = back;
  }
  querySelector(selector) {
    return selector === '#run-detail' ? this.box : this.back;
  }
}

function createContext() {
  const box = new DetailBox();
  const back = {};
  const context = vm.createContext({
    document: new PageDocument(box, back),
    location: { hash: '#job/task' },
    history: { pushState() {} },
    console, encodeURIComponent, decodeURIComponent,
  });
  const source = fs.readFileSync(path.join(__dirname, '../weshub/web/app.js'), 'utf8');
  vm.runInContext(source.split('/* pipeline dialog')[0], context);
  context.box = box;
  vm.runInContext(`state.jobs = [{namespace:'task', task:'demo', state:'FAILED', execution:{steps:[]}}]; selectedJob = 'task';`, context);
  return context;
}

function unchangedPollingPreservesDetailDOM() {
  const context = createContext();
  vm.runInContext('renderDetail(); renderDetail(); renderDetail();', context);
  assert.equal(context.box.writes, 1);
  assert.match(context.box.html, /<section class="job-step">/);
}

function stateChangesUpdateDetail() {
  const context = createContext();
  vm.runInContext(`renderDetail(); state.jobs[0].state = 'COMPLETED'; renderDetail();`, context);
  assert.equal(context.box.writes, 2);
  assert.match(context.box.html, /badge success/);
}

function folderChoiceSurvivesRendering() {
  const context = createContext();
  const html = vm.runInContext(`resultFolderStates.set('results/run', false); resultTree([{directory:true, path:'results/run', name:'run', children:[]}]);`, context);
  assert.doesNotMatch(html, /details[^>]* open/);
}

function sweepTasksSortNumerically() {
  const context = createContext();
  const html = vm.runInContext(`groupedJobDetails([{namespace:'ns_array_12',parent_namespace:'ns',array_index:'12'}, {namespace:'ns_array_2',parent_namespace:'ns',array_index:'2'}])`, context);
  assert.ok(html.indexOf('data-job-namespace="ns_array_2"') < html.indexOf('data-job-namespace="ns_array_12"'));
  assert.match(html, /data-sweep="ns"/);
}

function filtersMatchTaskAndState() {
  const context = createContext();
  const matches = vm.runInContext(`searchText = '81'; statusFilter = 'FAILED'; jobMatchesFilters({namespace:'sweep_array_81',state:'FAILED'})`, context);
  assert.equal(matches, true);
  const excluded = vm.runInContext(`jobMatchesFilters({namespace:'sweep_array_81',state:'RUNNING'})`, context);
  assert.equal(excluded, false);
}

function remoteFoldersStartCollapsedAndDoNotRenderChildren() {
  const context = createContext();
  const html = vm.runInContext(`remoteResultTree({entries:[{name:'results',path:'results',directory:true,children:[{name:'large.bin'}]}]}, 'task')`, context);
  assert.match(html, /data-remote-path="results"/);
  assert.doesNotMatch(html, /details[^>]* open/);
  assert.doesNotMatch(html, /large.bin/);
  assert.match(html, /Pull folder/);
}

function remoteFilesOfferDownloadUntilLocal() {
  const context = createContext();
  const remote = vm.runInContext(`remoteResultTree({entries:[{name:'chart.png',path:'results/chart.png',directory:false,size:100}]}, 'task')`, context);
  assert.match(remote, /data-pull-artifact="results\/chart.png"/);
  assert.doesNotMatch(remote, /href=/);
  const local = vm.runInContext(`remoteResultTree({entries:[{name:'chart.png',path:'results/chart.png',directory:false,size:100,downloaded:true,local_path:'task/results/chart.png'}]}, 'task')`, context);
  assert.match(local, /href="\/results\/task\/results\/chart.png"/);
}

test('unchanged polling preserves the detail DOM', unchangedPollingPreservesDetailDOM);
test('changed state updates detail and badge', stateChangesUpdateDetail);
test('closed result folders stay closed', folderChoiceSurvivesRendering);
test('sweep tasks sort by numeric index', sweepTasksSortNumerically);
test('filters match task identity and status together', filtersMatchTaskAndState);
test('remote folders start collapsed and list children lazily', remoteFoldersStartCollapsedAndDoNotRenderChildren);
test('remote files offer downloads and local files offer links', remoteFilesOfferDownloadUntilLocal);
