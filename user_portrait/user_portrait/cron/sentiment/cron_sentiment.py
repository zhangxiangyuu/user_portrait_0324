# -*- coding:utf-8 -*-
import os
import sys
import json
reload(sys)
sys.path.append('../../')
from global_utils import es_user_portrait, portrait_index_name,\
                      portrait_index_type, es_sentiment_task, sentiment_keywords_index_name ,\
                      sentiment_keywords_index_type, R_SENTIMENT_KEYWORDS,\
                      r_sentiment_keywords_name, es_flow_text, flow_text_index_name_pre, flow_text_index_type
from global_utils import es_sentiment_task, sentiment_keywords_index_name, \
        sentiment_keywords_index_type
from time_utils import ts2datetime, datetime2ts, ts2date
from parameter import SENTIMENT_TYPE_COUNT, Fifteen, SENTIMENT_MAX_KEYWORDS,\
        SENTIMENT_ITER_USER_COUNT, SENTIMENT_ITER_TEXT_COUNT, SENTIMENT_FIRST, DAY,\
        SENTIMENT_SECOND, DAY, str2segment

#use to read task information from redis queue
def get_task_information():
    try:
        results = R_SENTIMENT_KEYWORDS.rpop(r_sentiment_keywords_name)
    except:
        results = {}
    if results:
        task_information_dict = json.loads(results)
    else:
        task_information_dict = {}

    return task_information_dict

#use to identify the task is exist in es
def identify_task_exist(task_information_dict):
    task_id = task_information_dict['task_id']
    try:
        task_exist = es_sentiment_task.get(index=sentiment_keywords_index_name, \
                doc_type=sentiment_keywords_index_type, id=task_id)['_source']
    except:
        task_exist = {}
    if not task_exist:
        return False
    else:
        return True

#use to compute task sentiment trend
def compute_sentiment_task(sentiment_task_information):
    results = {}
    #step1: get task information
    start_date = sentiment_task_information['start_date']
    start_ts = datetime2ts(start_date)
    end_date = sentiment_task_information['end_date']
    end_ts = datetime2ts(end_date)
    iter_date_ts = start_ts
    to_date_ts = end_ts
    iter_query_date_list = [] # ['2013-09-01', '2013-09-02']
    while iter_date_ts <= to_date_ts:
        iter_date = ts2datetime(iter_date_ts)
        iter_query_date_list.append(iter_date)
        iter_date_ts += DAY
    #step2: get iter search flow_text_index_name
    #step2.1: get search keywords list
    query_must_list = []
    keyword_nest_body_list = []
    keywords_string = sentiment_task_information['query_keywords']
    keywords_list = keywords_string.split('&')
    for keywords_item in keywords_list:
        keyword_nest_body_list.append({'wildcard': {'text': '*' + keywords_item + '*'}})
    query_must_list.append({'bool': {'should': keyword_nest_body_list}})
    all_sentiment_dict = {}
    all_keyword_dict = {}
    iter_query_list = query_must_list
    #step2.2: iter search by date
    segment = sentiment_task_information['segment']
    segment_ts = str2segment[segment] # segment_ts = 900/3600/3600*24
    for iter_date in iter_query_date_list:
        flow_text_index_name = flow_text_index_name_pre + iter_date
        iter_start_ts = datetime2ts(iter_date)
        for i in range(0, DAY/segment_ts):
            query_start_ts = iter_start_ts + i * segment_ts
            iter_query_list.append({'range':{'timestamp':{'gte': query_start_ts, 'lt':query_start_ts + Fifteen}}})
            query_body = {
                'query':{
                    'bool':{
                        'must':iter_query_list
                    }
                },
                'aggs':{
                    'all_interests':{
                        'terms':{
                            'field': 'sentiment',
                            'size': SENTIMENT_TYPE_COUNT
                        }
                    }
                }
            }
            
            flow_text_result = es_flow_text.search(index=flow_text_index_name, doc_type=flow_text_index_type,\
                        body=query_body)['aggregations']['all_interests']['buckets']
            iter_query_list = iter_query_list[:-1]
            iter_sentiment_dict = {}
            for flow_text_item in flow_text_result:
                sentiment  = flow_text_item['key']
                sentiment_count = flow_text_item['doc_count']
                if sentiment in SENTIMENT_SECOND:
                    sentiment = '7'
                try:
                    iter_sentiment_dict[sentiment] += sentiment_count
                except:
                    iter_sentiment_dict[sentiment] = sentiment_count
            #add 0 to iter_sentiment_dict
            for sentiment in SENTIMENT_FIRST:
                try:
                    count = iter_sentiment_dict[sentiment]
                except:
                    iter_sentiment_dict[sentiment] = 0
            all_sentiment_dict[query_start_ts] = iter_sentiment_dict
    sort_sentiment_dict = sorted(all_sentiment_dict.items(), key=lambda x:x[0])
    trend_results = {}
    for sentiment in SENTIMENT_FIRST:
        trend_results[sentiment] = [[item[0], item[1][sentiment]] for item in sort_sentiment_dict]
    results = trend_results
    return results

def save_task_results(results, sentiment_task_information):
    status = True
    #step1:identify the task is exist in es
    exist_mark = identify_task_exist(sentiment_task_information)
    #step2:add the task results to es
    if exist_mark:
        task_id = sentiment_task_information['task_id']
        #try:
        es_sentiment_task.update(index=sentiment_keywords_index_name, \
                doc_type=sentiment_keywords_index_type, id=task_id, body={'doc': {'results':json.dumps(results), 'status': '1'}})
        #except:
        #    status = False
    return status

def push_task_information(sentiment_task_information):
    status = True
    try:
        R_SENTIMENT_KEYWORDS.lpush(r_sentiment_keywords_name, json.dumps(sentiment_task_information))
    except:
        status = False
    return status

#use to read task information from queue
def scan_sentiment_keywords_task():
    #step1: read task information from reids queue
    #step2: identify the task information is exist in es
    #step3: compute the sentiment trend task
    while True:
        #read task informaiton from redis queue
        sentiment_task_information = get_task_information()
        #test push
        #push_task_information(sentiment_task_information)
        #when redis queue null - file break
        if not sentiment_task_information:
            break
        #identify the task is exist in es
        exist_mark = identify_task_exist(sentiment_task_information)
        print 'exist_mark:', exist_mark
        if exist_mark:
            results = compute_sentiment_task(sentiment_task_information)
            #save results
            save_mark = save_task_results(results, sentiment_task_information)
            #identify save status
            if not save_mark:
                #status fail: push task information to redis queue
                push_mark = push_task_information(sentiment_task_information)
                if not push_mark:
                    print 'error push task queue'
        else:
            #if no exist - pass
            pass



if __name__=='__main__':
    log_time_ts = time.time()
    log_time_date = ts2datetime(log_time_ts)
    print 'cron/sentiment/cron_sentiment.py&start&' + log_time_date
    
    scan_sentiment_keywords_task()

    log_time_ts = time.time()
    log_time_date = ts2datetime(log_time_ts)
    print 'cron/sentiment/cron_sentiment.py&end&' + log_time_date
