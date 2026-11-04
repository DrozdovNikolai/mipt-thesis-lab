import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nord_session/api/client.dart';

void main() {
  test(
    'Refreshes an expired credential and repeats the original authorized request',
    () async {
      final paths = <String>[];
      final api = SessionApi(
        MockClient((r) async {
          paths.add(r.url.path.split('/').last);
          if (r.url.path.endsWith('/login'))
            return http.Response(
              '{"accessToken":"expired","refreshToken":"first"}',
              200,
            );
          if (r.url.path.endsWith('/refresh')) {
            expect(jsonDecode(r.body), {'refreshToken': 'first'});
            return http.Response(
              '{"accessToken":"new","refreshToken":"second"}',
              200,
            );
          }
          return r.headers['Authorization'] == 'Bearer new'
              ? http.Response('{"login":"student"}', 200)
              : http.Response('{}', 401);
        }),
      );
      await api.login('student', 'test');
      expect((await api.request('GET', '/auth/me'))['login'], 'student');
      expect(paths, ['login', 'me', 'refresh', 'me']);
    },
  );
}
