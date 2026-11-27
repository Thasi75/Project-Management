import type {Row} from './api';

export type MetricId='progress'|'total'|'completed'|'not_started'|'overdue'|'risks'|'changes'|'interfaces'|'coding'|'costs';
type MetricTarget={section:'tasks'|'risks'|'changes'|'interfaces'|'coding'|'costs';filters:Row;description:string};
export type MetricNavigationRequest=MetricTarget & {projectId:string;id:number};
const targets:Record<MetricId,MetricTarget>={
 progress:{section:'tasks',filters:{},description:'查看全部任务甘特图，项目进度按计划天数计算'},
 total:{section:'tasks',filters:{},description:'查看全部任务'},
 completed:{section:'tasks',filters:{status:'已完成'},description:'查看已完成任务'},
 not_started:{section:'tasks',filters:{status:'未开始'},description:'查看未开始任务'},
 overdue:{section:'tasks',filters:{overdue:true},description:'查看计划结束日期早于今天且未完成、未取消的任务'},
 risks:{section:'risks',filters:{status_ne:'已关闭'},description:'查看未关闭的项目风险'},
 changes:{section:'changes',filters:{},description:'查看全部需求变更'},
 interfaces:{section:'interfaces',filters:{status_ne:'上线'},description:'查看状态不等于上线的外部接口'},
 coding:{section:'coding',filters:{},description:'查看全部代码编写记录，耗时先累计分钟再取完整小时'},
 costs:{section:'costs',filters:{},description:'查看全部费用记录'},
};
export const metricTarget=(id:MetricId):MetricTarget=>targets[id];
