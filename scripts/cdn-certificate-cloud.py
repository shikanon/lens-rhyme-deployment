#!/usr/bin/env python3
"""SDK adapter executed inside the existing backend; secrets only arrive on stdin."""
import json
import sys


def main():
    data = json.load(sys.stdin)
    credentials = data['credentials']
    if data['operation'] == 'aliyun-api':
        from aliyunsdkcore.client import AcsClient
        from aliyunsdkcore.request import CommonRequest
        request = CommonRequest()
        request.set_domain('cdn.aliyuncs.com')
        request.set_version('2018-05-10')
        request.set_method('POST')
        request.set_action_name(data['action'])
        for key, value in data['params'].items():
            request.add_body_params(key, value)
        result = json.loads(AcsClient(credentials['ak'], credentials['sk'], 'cn-hangzhou').do_action_with_exception(request))
        # Never return configuration or private certificate material.
        return {'request_id': result.get('RequestId')}
    target = data['target']
    key = '.well-known/acme-challenge/' + data['token']
    if target['provider'] == 'volcengine':
        import tos
        client = tos.TosClientV2(credentials['ak'], credentials['sk'], target['endpoint'], target['region'])
        if data['operation'] == 'put':
            client.put_object(target['bucket'], key, content=data['validation'].encode(), content_type='text/plain', cache_control='no-cache, max-age=0')
        else:
            client.delete_object(target['bucket'], key)
    else:
        import oss2
        bucket = oss2.Bucket(oss2.Auth(credentials['ak'], credentials['sk']), target['endpoint'], target['bucket'])
        if data['operation'] == 'put':
            bucket.put_object(key, data['validation'], headers={'Content-Type':'text/plain','Cache-Control':'no-cache, max-age=0'})
        else:
            bucket.delete_object(key)
    return {'ok': True}


if __name__ == '__main__':
    try:
        print(json.dumps(main()))
    except Exception as error:
        # SDK exceptions can contain signed requests. Return a code only.
        print(json.dumps({'error': type(error).__name__, 'code': str(getattr(error, 'error_code', getattr(error, 'code', 'cloud_operation_failed')))}))
        sys.exit(1)
