Вот оформленный в формате Markdown документация на основе предоставленного вами Python и PHP кода. Этот файл можно сохранить как `API_DOC.md` в корне вашего репозитория.

---

# Документация API Домофонии (Dom.ru / Proptech)

Данная документация составлена на основе реверс-инжиниринга мобильного приложения и предоставленных исходных кодов.

## Общая информация
- **Base URL:** `https://myhome.proptech.ru/`
- **User-Agent:** `myHomeErth/3 CFNetwork/1240.0.4 Darwin/20.6.0` или `Xiaomi MIX2S | Android 10 | erth | 8.26.0`

## Заголовки (Headers)
Для большинства запросов требуются следующие заголовки:
- `Authorization: Bearer <access_token>`
- `Operator: <operator_id>`
- `Content-Type: application/json; charset=UTF-8`

---

## 1. Авторизация

### Получение кода (SMS)
**Endpoint:** `GET /auth/v2/login/{phone}`
**Описание:** Запрашивает отправку SMS-кода на указанный номер телефона.

### Подтверждение кода
**Endpoint:** `GET /auth/v2/confirmation/{phone}`
**Описание:** Проверка кода, полученного по SMS.

### Авторизация по логину и паролю (Hash)
**Endpoint:** `POST /auth/v2/auth/{login}/password`
**Тело запроса:**
```json
{
    "login": "780059056016",
    "timestamp": "2026-01-25T23:08:28.000Z",
    "hash1": "SHA1_Base64(password)",
    "hash2": "MD5(DigitalHomeNTKpassword + login + password + timestamp + 789sdgHJs678wertv34712376)"
}
```

**Ответ:**
```json
{
  "access_token": "x6gmp7qancrek4ztbie3kd8bmguubc...",
  "refresh_token": "0000022c-45a27c82-fdbe-2c07-e0...",
  "operator_id": 2,
  "token_type": "Bearer"
}
```

**Поля ответа:**
- `access_token` — Токен доступа для API (используется в заголовке `Authorization: Bearer <token>`)
- `refresh_token` — Токен для обновления доступа (используется при повторной авторизации)
- `operator_id` — ID оператора связи (используется в заголовке `Operator: <id>`)
- `token_type` — Тип токена (обычно "Bearer")

### Обновление токена (Refresh)
**Endpoint:** `GET /auth/v2/session/refresh`
**Headers:**
- `Bearer: <refresh_token>`
- `Operator: <operator_id>`
---

## 2. Структура и объекты

### Получение профиля пользователя
**Endpoint:** `GET /rest/v1/subscribers/profiles`
**Описание:** Возвращает информацию о профиле подписчика, включая ID, телефоны и настройки.

**Ответ:**
```json
{
  "data": {
    "subscriber": {
      "id": 2985851,
      "name": "Пользователь",
      "accountId": "7XXXXXXXXXX",
      "nickName": null
    },
    "pushUserId": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "callSelectedPlaceOnly": null,
    "subscriberPhones": [
      {
        "id": 2689738,
        "number": "7XXXXXXXXXX",
        "numberValid": true
      }
    ],
    "checkPhoneForSvcActivation": false,
    "allowAddPhone": false
  }
}
```

### Получение финансовой информации
**Endpoint:** `GET /rest/v1/subscribers/profiles/finances`
**Описание:** Возвращает информацию о балансе, блокировках и платежах.

**Ответ:**
```json
{
  "balance": 0.0,
  "blockType": "NOT_BLOCKED",
  "amountSum": 150.0,
  "targetDate": "2026-02-23T01:00:00Z",
  "paymentLink": "https://dom.ru/payments",
  "daysToBlock": null,
  "daysToWarning": null,
  "blocked": false
}
```

**Поля ответа:**
- `balance` — Текущий баланс
- `blockType` — Тип блокировки ("NOT_BLOCKED", "BLOCKED" и т.д.)
- `amountSum` — Сумма к оплате
- `targetDate` — Дата следующего платежа
- `paymentLink` — Ссылка для оплаты
- `blocked` — Заблокирован ли аккаунт

### Получение списка адресов (Subscriber Places)
**Endpoint:** `GET /rest/v3/subscriber-places`
**Описание:** Возвращает список объектов (квартир/домов), привязанных к аккаунту. Нужен для получения `placeId`.

**Ответ:**
```json
{
  "data": [
    {
      "id": 3066004,
      "subscriberType": "owner",
      "subscriberState": "out",
      "place": {
        "id": 5802693,
        "address": {
          "index": null,
          "region": null,
          "district": null,
          "city": "Санкт-Петербург г",
          "locality": null,
          "street": "Королёва пр-кт",
          "house": "19",
          "building": null,
          "apartment": "335",
          "visibleAddress": "Королёва пр-кт, д. 19, кв. 335",
          "groupName": "г. Санкт-Петербург"
        },
        "location": {
          "longitude": 30.28369,
          "latitude": 60.012966
        },
        "operatorId": 2,
        "autoArmingState": false,
        "autoArmingRadius": 0
      },
      "subscriber": {
        "id": 2985851,
        "name": "Пользователь",
        "accountId": "780059056016",
        "nickName": null
      },
      "guardCallOut": {
        "active": false,
        "phoneNumber": "+73832090399"
      },
      "payment": {
        "useLink": false
      },
      "provider": null,
      "blocked": false
    }
  ]
}
```

### Список устройств доступа (Домофоны)
**Endpoint:** `GET /rest/v1/places/{placeId}/accesscontrols`
**Описание:** Список домофонов для конкретного адреса. Возвращает `deviceId` (или `accessControlId`).

**Примечание:** На текущий момент в API могут не возвращаться access controls через этот эндпоинт для некоторых конфигураций. Открытие двери может быть недоступно для пользователя.

### Список камер
**Endpoint:** `GET /rest/v1/forpost/cameras`
**Описание:** Возвращает список всех доступных камер (включая домофонные и придомовые).

**Ответ:**
```json
{
  "data": [
    {
      "ID": 17098603,
      "Name": "Королева Пр-Кт 19  (п. 10)",
      "IsActive": 1,
      "IsSound": 1,
      "RecordType": 1,
      "Quota": 259200,
      "MaxBandwidth": null,
      "HomeMode": 0,
      "Devices": null,
      "ParentGroups": [
        {
          "ID": 14255,
          "Name": "Все камеры",
          "ParentID": 0
        },
        {
          "ID": 14307,
          "Name": "Домофон-Королева Пр-Кт 19 (10)",
          "ParentID": 0
        },
        {
          "ID": 21765,
          "Name": "ЖКС3",
          "ParentID": 0
        },
        {
          "ID": 66055,
          "Name": "СПб ГМЦ",
          "ParentID": 0
        }
      ],
      "State": 1,
      "TimeZone": 10800,
      "MotionDetectorMode": "UNKNOWN",
      "ParentID": "193895"
    }
  ]
}
```

---

## 3. Действия и управление

### Открытие двери
**Endpoint:** `POST /rest/v1/places/{placeId}/accesscontrols/{deviceId}/actions`
**Метод:** POST
**Тело запроса:**
```json
{"name": "accessControlOpen"}
```

### Временные коды (Temporal Codes)
**Endpoint:** `GET /rest/v1/temporal-codes?accessControlIds={id1,id2}`
**Описание:** Получение списка временных кодов для доступа.

---

## 4. Видео и Снапшоты

### Получение снапшота (Фото)
**Endpoint:** `GET /rest/v1/forpost/cameras/{cameraId}/snapshots`
**Описание:** Возвращает бинарные данные изображения (JPEG).

### Получение ссылки на видеопоток
**Endpoint:** `GET /rest/v1/forpost/cameras/{cameraId}/video?LightStream=0`
**Описание:** Возвращает JSON с URL-ссылкой на поток (обычно HLS/M3U8).

---

## 5. События и Уведомления

### Поиск событий (Polling)
**Endpoint:** `POST /rest/v1/events/search?page={page}&sort=occurredAt,DESC`
**Тело запроса:**
```json
{
    "placeIds": [12345, 67890]
}
```

### Список событий по адресу
**Endpoint:** `GET /rest/v1/places/{placeId}/events?allowExtentedActions=true`
**Описание:** Используется для отслеживания входящих вызовов и открытий дверей.

---

## Ошибки (Status Codes)
- `401 Unauthorized` — Токен истек, требуется обновление через Refresh.
- `403 Forbidden` — Требуется полная авторизация.
- `531 (Error 6007)` — Устройство недоступно.
- `500 (Error 6005)` — Ошибка при генерации временного кода.

---

### Примечания по реализации
1. **Hash2** для авторизации по паролю формируется как:
   `md5("DigitalHomeNTKpassword" + login + password + timestamp + "789sdgHJs678wertv34712376")`
2. **Polling событий:** Рекомендуемый интервал опроса эндпоинта событий для Home Assistant — 3-5 секунд.