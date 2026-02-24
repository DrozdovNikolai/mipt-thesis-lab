import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'config.dart';
import 'failure.dart';
import 'tokens.dart';

class SessionApi {
  final http.Client client;
  Tokens? tokens;
  SessionApi(this.client);

  Future<dynamic> send(String method,String path,{Object? body,Map<String,String>? query,Map<String,String>? headers,String? bearer}) async {
    final req=http.Request(method,apiUri(path,query));
    req.headers.addAll({'Accept':'application/json',if(bearer!=null)'Authorization':'Bearer $bearer', ...?headers});
    if(body!=null){req.headers['Content-Type']='application/json; charset=utf-8';req.body=jsonEncode(body);}
    final response=await client.send(req).then(http.Response.fromStream).timeout(const Duration(seconds:30));
    final raw=utf8.decode(response.bodyBytes);
    dynamic data;
    if(raw.isNotEmpty){try{data=jsonDecode(raw);}on FormatException{if(response.statusCode<400){throw const FormatException('Вместо JSON получен другой ответ. Проверьте адрес API.');}}}
    if(response.statusCode<200 || response.statusCode>=300){throw ApiFailure.from(response.statusCode,data);}
    return data;
  }
  Future<void> login(String login,String password) async {
    tokens=Tokens.from(await send('POST','/auth/login',body:{'login':login,'password':password}));
  }
  void logout(){tokens=null;}
}
