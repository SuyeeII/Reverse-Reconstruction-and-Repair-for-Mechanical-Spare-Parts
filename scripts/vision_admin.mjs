import {readFile} from 'node:fs/promises';
import {createClient,memoryJournal} from '../runtime/sdk-bundle.mjs';
const root=process.env.REPAIRFORGE_ROOT,home=process.env.AGH_HOME;
if(!root||home!==root+'/.agh')throw Error('Independent home required');
const owner=JSON.parse(await readFile(home+'/data/daemon/owner.json','utf8'));
const client=createClient({transport:{kind:'unix',path:owner.socketPath},auth:{kind:'local'},journal:memoryJournal()});
try{await client.initialize();const packages=await client.packages.list({profile:'local-dev'});console.log(JSON.stringify({packages}));}finally{await client.close();}
