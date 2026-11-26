export function groupPeopleByTeam<T extends Record<string,any>>(people:T[]) {
  const groups=new Map<string,T[]>();
  for(const person of people){
    const team=String(person.team||'').trim();
    if(!groups.has(team))groups.set(team,[]);
    groups.get(team)!.push(person);
  }
  return [...groups].sort(([a],[b])=>Number(!a)-Number(!b)||a.localeCompare(b,'zh-CN'))
    .map(([team,people])=>({team,label:team||'未填写单位 / 团队',people}));
}
