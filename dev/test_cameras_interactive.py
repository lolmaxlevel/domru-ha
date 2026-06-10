"""Interactive test for getting all cameras from Dom.ru API."""

import asyncio
import json
import os
import sys
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiohttp

from custom_components.domru.api import DomruApiClient


def print_header(text):
    """Print formatted header."""
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}\n")


def print_camera_info(camera, index):
    """Print camera information in a formatted way."""
    print(f"\n📹 Камера #{index}")
    print(f"{'─' * 60}")
    print(f"  ID: {camera.get('ID')}")
    print(f"  Название: {camera.get('Name')}")
    print(f"  Активна: {'✅ Да' if camera.get('IsActive') == 1 else '❌ Нет'}")
    print(f"  Звук: {'🔊 Да' if camera.get('IsSound') == 1 else '🔇 Нет'}")
    print(f"  Состояние: {'🟢 Онлайн' if camera.get('State') == 1 else '🔴 Оффлайн'}")
    print(f"  Режим записи: {camera.get('RecordType')}")
    print(f"  Квота (сек): {camera.get('Quota')}")
    print(f"  Часовой пояс: UTC+{camera.get('TimeZone', 0) // 3600}")
    print(f"  Детектор движения: {camera.get('MotionDetectorMode', 'UNKNOWN')}")

    if camera.get("ParentGroups"):
        print("  Группы:")
        for group in camera.get("ParentGroups", []):
            print(f"    • {group.get('Name')} (ID: {group.get('ID')})")


def print_menu():
    """Print interactive menu."""
    print("\n" + "═" * 60)
    print("  МЕНЮ ДЕЙСТВИЙ")
    print("═" * 60)
    print("  1. Показать все камеры")
    print("  2. Показать активные камеры")
    print("  3. Показать камеры со звуком")
    print("  4. Показать камеры в конкретной группе")
    print("  5. Получить подробную информацию о камере")
    print("  6. Получить snapshot (фото) с камеры")
    print("  7. Получить URL видеопотока")
    print("  8. Сохранить все данные в JSON файл")
    print("  0. Выход")
    print("═" * 60)


def redact_url(value):
    """Return a safe display value for signed stream URLs."""
    if not value:
        return "<missing>"
    return f"{value[:12]}...<redacted>" if len(value) > 12 else "<redacted>"


async def get_camera_snapshot(client, camera_id):
    """Get camera snapshot and save to file."""
    try:
        print(f"\n📸 Получаем snapshot с камеры {camera_id}...")
        snapshot_data = await client.async_get_camera_snapshot(camera_id)

        if snapshot_data:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"camera_{camera_id}_{timestamp}.jpg"

            with open(filename, "wb") as f:
                f.write(snapshot_data)

            print(f"✅ Snapshot сохранен: {filename}")
            print(f"   Размер: {len(snapshot_data)} байт")
            return True
        print("❌ Не удалось получить snapshot")
        return False
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False


async def get_camera_stream_url(client, camera_id):
    """Get camera stream URL."""
    try:
        print(f"\n🎥 Получаем URL видеопотока для камеры {camera_id}...")
        stream_url = await client.async_get_camera_stream_url(camera_id)

        if stream_url:
            print("✅ URL видеопотока:")
            print(f"   {redact_url(stream_url)}")

            # Определяем тип потока
            if stream_url.startswith("rtsp://"):
                print("\n   📡 Тип: RTSP поток")
                print("   💡 Можно открыть в VLC с полученным URL")
            elif ".m3u8" in stream_url:
                print("\n   📡 Тип: HLS поток (M3U8)")
                print("   💡 Можно открыть в браузере или VLC")

            return stream_url
        print("❌ Не удалось получить URL")
        return None
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return None


async def interactive_menu(client, cameras):
    """Interactive menu for working with cameras."""
    while True:
        print_menu()
        choice = input("\nВыберите действие (0-8): ").strip()

        if choice == "0":
            print("\n👋 До свидания!")
            break

        if choice == "1":
            # Показать все камеры
            print_header("ВСЕ КАМЕРЫ")
            for i, camera in enumerate(cameras, 1):
                print_camera_info(camera, i)

        elif choice == "2":
            # Активные камеры
            print_header("АКТИВНЫЕ КАМЕРЫ")
            active = [c for c in cameras if c.get("IsActive") == 1]
            if active:
                for i, camera in enumerate(active, 1):
                    print_camera_info(camera, i)
            else:
                print("❌ Нет активных камер")

        elif choice == "3":
            # Камеры со звуком
            print_header("КАМЕРЫ СО ЗВУКОМ")
            with_sound = [c for c in cameras if c.get("IsSound") == 1]
            if with_sound:
                for i, camera in enumerate(with_sound, 1):
                    print_camera_info(camera, i)
            else:
                print("❌ Нет камер со звуком")

        elif choice == "4":
            # Камеры по группе
            print_header("ГРУППЫ КАМЕР")
            groups = set()
            for camera in cameras:
                for group in camera.get("ParentGroups", []):
                    groups.add((group.get("ID"), group.get("Name")))

            groups_list = sorted(list(groups), key=lambda x: x[1])

            if groups_list:
                for i, (group_id, group_name) in enumerate(groups_list, 1):
                    print(f"  {i}. {group_name} (ID: {group_id})")

                group_choice = input(
                    f"\nВыберите группу (1-{len(groups_list)}): "
                ).strip()
                try:
                    group_idx = int(group_choice) - 1
                    if 0 <= group_idx < len(groups_list):
                        selected_group_id = groups_list[group_idx][0]
                        selected_group_name = groups_list[group_idx][1]

                        print_header(f"КАМЕРЫ В ГРУППЕ: {selected_group_name}")
                        group_cameras = []
                        for camera in cameras:
                            for group in camera.get("ParentGroups", []):
                                if group.get("ID") == selected_group_id:
                                    group_cameras.append(camera)
                                    break

                        for i, camera in enumerate(group_cameras, 1):
                            print_camera_info(camera, i)
                    else:
                        print("❌ Неверный выбор")
                except ValueError:
                    print("❌ Введите число")
            else:
                print("❌ Нет групп")

        elif choice == "5":
            # Подробная информация
            print_header("ПОДРОБНАЯ ИНФОРМАЦИЯ О КАМЕРЕ")
            for i, camera in enumerate(cameras, 1):
                print(f"  {i}. {camera.get('Name')} (ID: {camera.get('ID')})")

            cam_choice = input(f"\nВыберите камеру (1-{len(cameras)}): ").strip()
            try:
                cam_idx = int(cam_choice) - 1
                if 0 <= cam_idx < len(cameras):
                    print("\n" + "=" * 60)
                    print(json.dumps(cameras[cam_idx], indent=2, ensure_ascii=False))
                    print("=" * 60)
                else:
                    print("❌ Неверный выбор")
            except ValueError:
                print("❌ Введите число")

        elif choice == "6":
            # Получить snapshot
            print_header("ПОЛУЧИТЬ SNAPSHOT")
            for i, camera in enumerate(cameras, 1):
                status = "🟢" if camera.get("State") == 1 else "🔴"
                print(f"  {i}. {status} {camera.get('Name')} (ID: {camera.get('ID')})")

            cam_choice = input(f"\nВыберите камеру (1-{len(cameras)}): ").strip()
            try:
                cam_idx = int(cam_choice) - 1
                if 0 <= cam_idx < len(cameras):
                    camera_id = cameras[cam_idx].get("ID")
                    await get_camera_snapshot(client, camera_id)
                else:
                    print("❌ Неверный выбор")
            except ValueError:
                print("❌ Введите число")

        elif choice == "7":
            # Получить URL видеопотока
            print_header("ПОЛУЧИТЬ URL ВИДЕОПОТОКА")
            for i, camera in enumerate(cameras, 1):
                status = "🟢" if camera.get("State") == 1 else "🔴"
                print(f"  {i}. {status} {camera.get('Name')} (ID: {camera.get('ID')})")

            cam_choice = input(f"\nВыберите камеру (1-{len(cameras)}): ").strip()
            try:
                cam_idx = int(cam_choice) - 1
                if 0 <= cam_idx < len(cameras):
                    camera_id = cameras[cam_idx].get("ID")
                    await get_camera_stream_url(client, camera_id)
                else:
                    print("❌ Неверный выбор")
            except ValueError:
                print("❌ Введите число")

        elif choice == "8":
            # Сохранить в JSON
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"cameras_data_{timestamp}.json"

            with open(filename, "w", encoding="utf-8") as f:
                json.dump(cameras, f, indent=2, ensure_ascii=False)

            print(f"\n✅ Данные сохранены в файл: {filename}")

        else:
            print("❌ Неверный выбор, попробуйте снова")

        input("\n\nНажмите Enter для продолжения...")


async def main():
    """Main function."""
    print_header("🎥 ТЕСТ API: ПОЛУЧЕНИЕ КАМЕР DOM.RU")

    # Read credentials
    username = input("Введите username (телефон): ").strip()
    password = input("Введите пароль: ").strip()

    if not username or not password:
        print("❌ Необходимо ввести username и пароль")
        return

    async with aiohttp.ClientSession() as session:
        client = DomruApiClient(
            username=username,
            password=password,
            session=session,
        )

        print("\n🔐 Авторизация...")
        try:
            await client.async_authenticate()
            print("✅ Авторизация успешна")
        except Exception as e:
            print(f"❌ Ошибка авторизации: {e}")
            return

        print("\n📡 Получение списка камер...")
        try:
            cameras = await client.get_cameras()

            if not cameras:
                print("❌ Камеры не найдены")
                return

            print(f"✅ Найдено камер: {len(cameras)}")

            # Статистика
            active_count = sum(1 for c in cameras if c.get("IsActive") == 1)
            online_count = sum(1 for c in cameras if c.get("State") == 1)
            sound_count = sum(1 for c in cameras if c.get("IsSound") == 1)

            print("\n📊 Статистика:")
            print(f"   Активных: {active_count}/{len(cameras)}")
            print(f"   Онлайн: {online_count}/{len(cameras)}")
            print(f"   Со звуком: {sound_count}/{len(cameras)}")

            # Interactive menu
            await interactive_menu(client, cameras)

        except Exception as e:
            print(f"❌ Ошибка получения камер: {e}")
            import traceback

            traceback.print_exc()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Прервано пользователем")
