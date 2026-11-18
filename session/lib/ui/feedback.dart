import 'dart:async';
import 'package:flutter/material.dart';
import 'package:http/http.dart';
import '../api/failure.dart';

String errorText(Object error) {
  if (error is TimeoutException || error is ClientException) {
    return 'Нет ответа от API. Проверьте подключение и адрес сервера.';
  }
  if (error is ApiFailure && error.status == 409) {
    return 'Конфликт сохранения. Другой редактор занял или изменил сценарий.';
  }
  if (error is ApiFailure && error.status == 403) {
    return 'Для этой операции недостаточно прав.';
  }
  return error.toString();
}

void notify(BuildContext context, String message) =>
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
