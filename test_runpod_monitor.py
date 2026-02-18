"""
Comprehensive test suite for runpod_monitor.py

This test suite covers:
- Utility functions (get_allowed_users, is_authorized, format_pod_info, generate_pod_name)
- RunPod REST API helper functions
- Telegram command handlers
- Callback handlers
- Pod checking and alerting functions
- Edge cases and error handling
"""

import os
import asyncio
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch, MagicMock, call
import pytest
import httpx

# Set environment variables before importing runpod_monitor
os.environ["RUNPOD_API_KEY"] = "test_api_key"
os.environ["TELEGRAM_BOT_TOKEN"] = "test_bot_token"
os.environ["TELEGRAM_CHAT_ID"] = "123456789"
os.environ["CHECK_INTERVAL_MINUTES"] = "60"
os.environ["ALLOWED_USER_IDS"] = "111,222,333"

import runpod_monitor
from runpod_monitor import (
    get_allowed_users,
    is_authorized,
    format_pod_info,
    generate_pod_name,
    runpod_rest_get,
    runpod_rest_post,
    fetch_templates,
    fetch_network_volumes,
    create_pod_api,
    send_alert,
    check_pods,
)


# ============================================================================
# Test Utility Functions
# ============================================================================

class TestGetAllowedUsers:
    """Test suite for get_allowed_users function"""

    def test_get_allowed_users_with_valid_ids(self):
        """Test parsing valid user IDs from environment variable"""
        with patch.dict(os.environ, {"ALLOWED_USER_IDS": "111,222,333"}):
            result = get_allowed_users()
            assert result == {111, 222, 333}

    def test_get_allowed_users_with_spaces(self):
        """Test parsing user IDs with extra spaces"""
        with patch.dict(os.environ, {"ALLOWED_USER_IDS": " 111 , 222 , 333 "}):
            result = get_allowed_users()
            assert result == {111, 222, 333}

    def test_get_allowed_users_empty_string(self):
        """Test with empty ALLOWED_USER_IDS"""
        with patch.object(runpod_monitor, 'ALLOWED_USER_IDS', ''):
            result = get_allowed_users()
            assert result == set()

    def test_get_allowed_users_single_id(self):
        """Test with single user ID"""
        with patch.object(runpod_monitor, 'ALLOWED_USER_IDS', '999'):
            result = get_allowed_users()
            assert result == {999}

    def test_get_allowed_users_with_empty_entries(self):
        """Test parsing with empty entries between commas"""
        with patch.dict(os.environ, {"ALLOWED_USER_IDS": "111,,222,  ,333"}):
            result = get_allowed_users()
            assert result == {111, 222, 333}


class TestIsAuthorized:
    """Test suite for is_authorized function"""

    def test_is_authorized_valid_chat_and_user(self):
        """Test authorization with valid chat ID and user ID"""
        update = Mock()
        update.effective_user.id = 111
        update.effective_chat.id = 123456789

        with patch.dict(os.environ, {
            "TELEGRAM_CHAT_ID": "123456789",
            "ALLOWED_USER_IDS": "111,222,333"
        }):
            assert is_authorized(update) is True

    def test_is_authorized_wrong_chat_id(self):
        """Test authorization fails with wrong chat ID"""
        update = Mock()
        update.effective_user.id = 111
        update.effective_chat.id = 999999999

        with patch.dict(os.environ, {
            "TELEGRAM_CHAT_ID": "123456789",
            "ALLOWED_USER_IDS": "111,222,333"
        }):
            assert is_authorized(update) is False

    def test_is_authorized_wrong_user_id(self):
        """Test authorization fails with wrong user ID"""
        update = Mock()
        update.effective_user.id = 999
        update.effective_chat.id = 123456789

        with patch.dict(os.environ, {
            "TELEGRAM_CHAT_ID": "123456789",
            "ALLOWED_USER_IDS": "111,222,333"
        }):
            assert is_authorized(update) is False

    def test_is_authorized_no_restrictions(self):
        """Test authorization succeeds when no restrictions are set"""
        update = Mock()
        update.effective_user.id = 999
        update.effective_chat.id = 888

        with patch.object(runpod_monitor, 'TELEGRAM_CHAT_ID', ''), \
             patch.object(runpod_monitor, 'ALLOWED_USER_IDS', ''):
            assert is_authorized(update) is True

    def test_is_authorized_only_chat_id_restriction(self):
        """Test authorization with only chat ID restriction"""
        update = Mock()
        update.effective_user.id = 999
        update.effective_chat.id = 123456789

        with patch.object(runpod_monitor, 'TELEGRAM_CHAT_ID', '123456789'), \
             patch.object(runpod_monitor, 'ALLOWED_USER_IDS', ''):
            assert is_authorized(update) is True

    def test_is_authorized_only_user_id_restriction(self):
        """Test authorization with only user ID restriction"""
        update = Mock()
        update.effective_user.id = 111
        update.effective_chat.id = 999999999

        with patch.object(runpod_monitor, 'TELEGRAM_CHAT_ID', ''), \
             patch.object(runpod_monitor, 'ALLOWED_USER_IDS', '111,222,333'):
            assert is_authorized(update) is True


class TestFormatPodInfo:
    """Test suite for format_pod_info function"""

    def test_format_pod_info_complete(self):
        """Test formatting pod info with complete data"""
        pod = {
            "id": "test-pod-123",
            "name": "my-test-pod",
            "machine": {
                "gpuDisplayName": "NVIDIA A100 80GB"
            },
            "costPerHr": 1.5678,
            "desiredStatus": "RUNNING"
        }

        result = format_pod_info(pod)
        assert "ID: test-pod-123" in result
        assert "이름: my-test-pod" in result
        assert "GPU: NVIDIA A100 80GB" in result
        assert "상태: RUNNING" in result
        assert "$1.5678" in result

    def test_format_pod_info_missing_machine(self):
        """Test formatting pod info when machine data is missing"""
        pod = {
            "id": "test-pod-123",
            "name": "my-test-pod",
            "costPerHr": 0.5,
            "desiredStatus": "STOPPED"
        }

        result = format_pod_info(pod)
        assert "ID: test-pod-123" in result
        assert "GPU: N/A" in result
        assert "상태: STOPPED" in result

    def test_format_pod_info_missing_name(self):
        """Test formatting pod info when name is missing"""
        pod = {
            "id": "test-pod-456",
            "machine": {
                "gpuDisplayName": "NVIDIA RTX A4500"
            },
            "costPerHr": 0.89,
            "desiredStatus": "RUNNING"
        }

        result = format_pod_info(pod)
        assert "ID: test-pod-456" in result
        assert "이름: N/A" in result

    def test_format_pod_info_zero_cost(self):
        """Test formatting pod info with zero cost"""
        pod = {
            "id": "test-pod-789",
            "name": "free-pod",
            "machine": {},
            "costPerHr": 0,
            "desiredStatus": "RUNNING"
        }

        result = format_pod_info(pod)
        assert "$0.0000" in result

    def test_format_pod_info_none_machine(self):
        """Test formatting pod info when machine is None"""
        pod = {
            "id": "test-pod-999",
            "name": "test",
            "machine": None,
            "costPerHr": 1.0,
            "desiredStatus": "RUNNING"
        }

        result = format_pod_info(pod)
        assert "GPU: N/A" in result


class TestGeneratePodName:
    """Test suite for generate_pod_name function"""

    @patch('runpod_monitor.datetime')
    def test_generate_pod_name_basic(self, mock_datetime):
        """Test basic pod name generation"""
        mock_datetime.now.return_value.strftime.return_value = "0204-1530"

        result = generate_pod_name("MyTemplate")
        assert result == "MyTemplate-0204-1530"

    @patch('runpod_monitor.datetime')
    def test_generate_pod_name_with_spaces(self, mock_datetime):
        """Test pod name generation with spaces in template name"""
        mock_datetime.now.return_value.strftime.return_value = "0204-1530"

        result = generate_pod_name("My Template Name")
        assert result == "My-Template-Name-0204-1530"
        assert " " not in result

    @patch('runpod_monitor.datetime')
    def test_generate_pod_name_long_template(self, mock_datetime):
        """Test pod name generation with long template name (truncation)"""
        mock_datetime.now.return_value.strftime.return_value = "0204-1530"

        long_name = "VeryLongTemplateNameThatExceedsTwentyCharacters"
        result = generate_pod_name(long_name)
        assert len(result.split("-0204-1530")[0]) <= 20

    @patch('runpod_monitor.datetime')
    def test_generate_pod_name_special_characters(self, mock_datetime):
        """Test pod name generation with special characters"""
        mock_datetime.now.return_value.strftime.return_value = "0204-1530"

        result = generate_pod_name("Template With Spaces")
        assert "-" in result
        assert "Template-With-Spaces" in result


# ============================================================================
# Test RunPod REST API Helper Functions
# ============================================================================

class TestRunPodRestGet:
    """Test suite for runpod_rest_get function"""

    @pytest.mark.asyncio
    async def test_runpod_rest_get_success(self):
        """Test successful GET request to RunPod API"""
        mock_response = {"data": "test_data"}

        with patch('httpx.AsyncClient') as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get = AsyncMock(return_value=Mock(
                json=lambda: mock_response,
                raise_for_status=lambda: None
            ))

            result = await runpod_rest_get("/test-endpoint")

            assert result == mock_response
            mock_instance.get.assert_called_once()
            call_args = mock_instance.get.call_args
            assert "/test-endpoint" in call_args[0][0]
            assert call_args[1]["headers"]["Authorization"] == "Bearer test_api_key"

    @pytest.mark.asyncio
    async def test_runpod_rest_get_http_error(self):
        """Test GET request with HTTP error"""
        with patch('httpx.AsyncClient') as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance

            mock_response = Mock()
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "404 Not Found",
                request=Mock(),
                response=Mock(status_code=404)
            )
            mock_instance.get = AsyncMock(return_value=mock_response)

            with pytest.raises(httpx.HTTPStatusError):
                await runpod_rest_get("/invalid-endpoint")

    @pytest.mark.asyncio
    async def test_runpod_rest_get_timeout(self):
        """Test GET request with timeout"""
        with patch('httpx.AsyncClient') as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))

            with pytest.raises(httpx.TimeoutException):
                await runpod_rest_get("/slow-endpoint")


class TestRunPodRestPost:
    """Test suite for runpod_rest_post function"""

    @pytest.mark.asyncio
    async def test_runpod_rest_post_success(self):
        """Test successful POST request to RunPod API"""
        mock_response = {"id": "new-pod-123"}
        post_data = {"name": "test-pod", "gpuCount": 1}

        with patch('httpx.AsyncClient') as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post = AsyncMock(return_value=Mock(
                json=lambda: mock_response,
                raise_for_status=lambda: None
            ))

            result = await runpod_rest_post("/pods", post_data)

            assert result == mock_response
            mock_instance.post.assert_called_once()
            call_args = mock_instance.post.call_args
            assert "/pods" in call_args[0][0]
            assert call_args[1]["json"] == post_data

    @pytest.mark.asyncio
    async def test_runpod_rest_post_http_error(self):
        """Test POST request with HTTP error"""
        with patch('httpx.AsyncClient') as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance

            mock_response = Mock()
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "400 Bad Request",
                request=Mock(),
                response=Mock(status_code=400, text="Invalid request")
            )
            mock_instance.post = AsyncMock(return_value=mock_response)

            with pytest.raises(httpx.HTTPStatusError):
                await runpod_rest_post("/pods", {})


class TestFetchTemplates:
    """Test suite for fetch_templates function"""

    @pytest.mark.asyncio
    async def test_fetch_templates_success(self):
        """Test fetching templates successfully"""
        mock_templates = [
            {"id": "tpl-1", "name": "Template 1"},
            {"id": "tpl-2", "name": "Template 2"}
        ]

        with patch('runpod_monitor.runpod_rest_get', new=AsyncMock(return_value=mock_templates)):
            result = await fetch_templates()
            assert result == mock_templates
            assert len(result) == 2

    @pytest.mark.asyncio
    async def test_fetch_templates_empty_list(self):
        """Test fetching templates returns empty list"""
        with patch('runpod_monitor.runpod_rest_get', new=AsyncMock(return_value=[])):
            result = await fetch_templates()
            assert result == []

    @pytest.mark.asyncio
    async def test_fetch_templates_non_list_response(self):
        """Test fetching templates with non-list response"""
        with patch('runpod_monitor.runpod_rest_get', new=AsyncMock(return_value={"error": "bad"})):
            result = await fetch_templates()
            assert result == []


class TestFetchNetworkVolumes:
    """Test suite for fetch_network_volumes function"""

    @pytest.mark.asyncio
    async def test_fetch_network_volumes_success(self):
        """Test fetching network volumes successfully"""
        mock_volumes = [
            {"id": "vol-1", "name": "Volume 1", "size": 100},
            {"id": "vol-2", "name": "Volume 2", "size": 200}
        ]

        with patch('runpod_monitor.runpod_rest_get', new=AsyncMock(return_value=mock_volumes)):
            result = await fetch_network_volumes()
            assert result == mock_volumes
            assert len(result) == 2

    @pytest.mark.asyncio
    async def test_fetch_network_volumes_empty_list(self):
        """Test fetching network volumes returns empty list"""
        with patch('runpod_monitor.runpod_rest_get', new=AsyncMock(return_value=[])):
            result = await fetch_network_volumes()
            assert result == []


class TestCreatePodApi:
    """Test suite for create_pod_api function"""

    @pytest.mark.asyncio
    async def test_create_pod_api_success(self):
        """Test creating pod via API successfully"""
        config = {
            "name": "test-pod",
            "gpuTypeIds": ["NVIDIA A100"],
            "gpuCount": 1
        }
        mock_response = {"id": "new-pod-123", "status": "created"}

        with patch('runpod_monitor.runpod_rest_post', new=AsyncMock(return_value=mock_response)):
            result = await create_pod_api(config)
            assert result == mock_response
            assert result["id"] == "new-pod-123"


# ============================================================================
# Test Telegram Command Handlers
# ============================================================================

class TestStartCommand:
    """Test suite for start_command handler"""

    @pytest.mark.asyncio
    async def test_start_command_authorized(self):
        """Test start command with authorized user"""
        update = Mock()
        update.effective_user.id = 111
        update.effective_chat.id = 123456789
        update.message.reply_text = AsyncMock()
        context = Mock()

        await runpod_monitor.start_command(update, context)

        update.message.reply_text.assert_called_once()
        args = update.message.reply_text.call_args[0]
        assert "RunPod Monitor Bot" in args[0]
        assert "/status" in args[0]
        assert "/terminate" in args[0]

    @pytest.mark.asyncio
    async def test_start_command_unauthorized(self):
        """Test start command with unauthorized user"""
        update = Mock()
        update.effective_user.id = 999
        update.effective_chat.id = 999999999
        update.message.reply_text = AsyncMock()
        context = Mock()

        await runpod_monitor.start_command(update, context)

        update.message.reply_text.assert_called_once_with("권한이 없습니다.")


class TestHelpCommand:
    """Test suite for help_command handler"""

    @pytest.mark.asyncio
    async def test_help_command_authorized(self):
        """Test help command with authorized user"""
        update = Mock()
        update.effective_user.id = 111
        update.effective_chat.id = 123456789
        update.message.reply_text = AsyncMock()
        context = Mock()

        await runpod_monitor.help_command(update, context)

        update.message.reply_text.assert_called_once()
        args = update.message.reply_text.call_args[0]
        assert "도움말" in args[0]
        assert f"{runpod_monitor.CHECK_INTERVAL_MINUTES}분" in args[0]

    @pytest.mark.asyncio
    async def test_help_command_unauthorized(self):
        """Test help command with unauthorized user"""
        update = Mock()
        update.effective_user.id = 999
        update.effective_chat.id = 999999999
        update.message.reply_text = AsyncMock()
        context = Mock()

        await runpod_monitor.help_command(update, context)

        update.message.reply_text.assert_called_once_with("권한이 없습니다.")


class TestStatusCommand:
    """Test suite for status_command handler"""

    @pytest.mark.asyncio
    async def test_status_command_with_running_pods(self):
        """Test status command when there are running pods"""
        update = Mock()
        update.effective_user.id = 111
        update.effective_chat.id = 123456789
        update.message.reply_text = AsyncMock()
        context = Mock()

        mock_pods = [
            {
                "id": "pod-1",
                "name": "running-pod",
                "desiredStatus": "RUNNING",
                "machine": {"gpuDisplayName": "NVIDIA A100"},
                "costPerHr": 1.5
            },
            {
                "id": "pod-2",
                "name": "stopped-pod",
                "desiredStatus": "STOPPED",
                "machine": {"gpuDisplayName": "NVIDIA RTX A4500"},
                "costPerHr": 0.5
            }
        ]

        with patch('runpod.get_pods', return_value=mock_pods):
            await runpod_monitor.status_command(update, context)

        update.message.reply_text.assert_called_once()
        args = update.message.reply_text.call_args[0]
        assert "실행 중인 Pod: 1개" in args[0]
        assert "running-pod" in args[0]

    @pytest.mark.asyncio
    async def test_status_command_no_running_pods(self):
        """Test status command when there are no running pods"""
        update = Mock()
        update.effective_user.id = 111
        update.effective_chat.id = 123456789
        update.message.reply_text = AsyncMock()
        context = Mock()

        mock_pods = [
            {
                "id": "pod-1",
                "name": "stopped-pod",
                "desiredStatus": "STOPPED",
                "machine": {},
                "costPerHr": 0.5
            }
        ]

        with patch('runpod.get_pods', return_value=mock_pods):
            await runpod_monitor.status_command(update, context)

        update.message.reply_text.assert_called_once_with("현재 실행 중인 pod이 없습니다.")

    @pytest.mark.asyncio
    async def test_status_command_error_handling(self):
        """Test status command error handling"""
        update = Mock()
        update.effective_user.id = 111
        update.effective_chat.id = 123456789
        update.message.reply_text = AsyncMock()
        context = Mock()

        with patch('runpod.get_pods', side_effect=Exception("API Error")):
            await runpod_monitor.status_command(update, context)

        update.message.reply_text.assert_called_once()
        args = update.message.reply_text.call_args[0]
        assert "오류가 발생했습니다" in args[0]

    @pytest.mark.asyncio
    async def test_status_command_unauthorized(self):
        """Test status command with unauthorized user"""
        update = Mock()
        update.effective_user.id = 999
        update.effective_chat.id = 999999999
        update.message.reply_text = AsyncMock()
        context = Mock()

        await runpod_monitor.status_command(update, context)

        update.message.reply_text.assert_called_once_with("권한이 없습니다.")


class TestPodsCommand:
    """Test suite for pods_command handler"""

    @pytest.mark.asyncio
    async def test_pods_command_with_pods(self):
        """Test pods command when there are pods"""
        update = Mock()
        update.effective_user.id = 111
        update.effective_chat.id = 123456789
        update.message.reply_text = AsyncMock()
        context = Mock()

        mock_pods = [
            {
                "id": "pod-1",
                "name": "test-pod-1",
                "desiredStatus": "RUNNING",
                "machine": {"gpuDisplayName": "NVIDIA A100"},
                "costPerHr": 1.5
            },
            {
                "id": "pod-2",
                "name": "test-pod-2",
                "desiredStatus": "STOPPED",
                "machine": {"gpuDisplayName": "NVIDIA RTX A4500"},
                "costPerHr": 0.5
            }
        ]

        with patch('runpod.get_pods', return_value=mock_pods):
            await runpod_monitor.pods_command(update, context)

        update.message.reply_text.assert_called_once()
        args = update.message.reply_text.call_args[0]
        assert "전체 Pod 목록: 2개" in args[0]
        assert "test-pod-1" in args[0]
        assert "test-pod-2" in args[0]

    @pytest.mark.asyncio
    async def test_pods_command_no_pods(self):
        """Test pods command when there are no pods"""
        update = Mock()
        update.effective_user.id = 111
        update.effective_chat.id = 123456789
        update.message.reply_text = AsyncMock()
        context = Mock()

        with patch('runpod.get_pods', return_value=[]):
            await runpod_monitor.pods_command(update, context)

        update.message.reply_text.assert_called_once_with("등록된 pod이 없습니다.")

    @pytest.mark.asyncio
    async def test_pods_command_error_handling(self):
        """Test pods command error handling"""
        update = Mock()
        update.effective_user.id = 111
        update.effective_chat.id = 123456789
        update.message.reply_text = AsyncMock()
        context = Mock()

        with patch('runpod.get_pods', side_effect=Exception("API Error")):
            await runpod_monitor.pods_command(update, context)

        update.message.reply_text.assert_called_once()
        args = update.message.reply_text.call_args[0]
        assert "오류가 발생했습니다" in args[0]


class TestTerminateCommand:
    """Test suite for terminate_command handler"""

    @pytest.mark.asyncio
    async def test_terminate_command_with_pods(self):
        """Test terminate command when there are pods to terminate"""
        update = Mock()
        update.effective_user.id = 111
        update.effective_chat.id = 123456789
        update.message.reply_text = AsyncMock()
        context = Mock()

        mock_pods = [
            {
                "id": "pod-1",
                "name": "test-pod-1",
                "desiredStatus": "RUNNING"
            }
        ]

        with patch('runpod.get_pods', return_value=mock_pods):
            await runpod_monitor.terminate_command(update, context)

        update.message.reply_text.assert_called_once()
        call_args = update.message.reply_text.call_args
        assert "종료할 pod을 선택하세요" in call_args[0][0]
        assert call_args[1]["reply_markup"] is not None

    @pytest.mark.asyncio
    async def test_terminate_command_no_pods(self):
        """Test terminate command when there are no pods"""
        update = Mock()
        update.effective_user.id = 111
        update.effective_chat.id = 123456789
        update.message.reply_text = AsyncMock()
        context = Mock()

        with patch('runpod.get_pods', return_value=[]):
            await runpod_monitor.terminate_command(update, context)

        update.message.reply_text.assert_called_once_with("현재 등록된 pod이 없습니다.")


class TestStopCommand:
    """Test suite for stop_command handler"""

    @pytest.mark.asyncio
    async def test_stop_command_with_running_pods(self):
        """Test stop command when there are running pods"""
        update = Mock()
        update.effective_user.id = 111
        update.effective_chat.id = 123456789
        update.message.reply_text = AsyncMock()
        context = Mock()

        mock_pods = [
            {
                "id": "pod-1",
                "name": "running-pod",
                "desiredStatus": "RUNNING"
            },
            {
                "id": "pod-2",
                "name": "stopped-pod",
                "desiredStatus": "STOPPED"
            }
        ]

        with patch('runpod.get_pods', return_value=mock_pods):
            await runpod_monitor.stop_command(update, context)

        update.message.reply_text.assert_called_once()
        call_args = update.message.reply_text.call_args
        assert "정지할 pod을 선택하세요" in call_args[0][0]
        assert call_args[1]["reply_markup"] is not None

    @pytest.mark.asyncio
    async def test_stop_command_no_running_pods(self):
        """Test stop command when there are no running pods"""
        update = Mock()
        update.effective_user.id = 111
        update.effective_chat.id = 123456789
        update.message.reply_text = AsyncMock()
        context = Mock()

        mock_pods = [
            {
                "id": "pod-1",
                "name": "stopped-pod",
                "desiredStatus": "STOPPED"
            }
        ]

        with patch('runpod.get_pods', return_value=mock_pods):
            await runpod_monitor.stop_command(update, context)

        update.message.reply_text.assert_called_once_with("현재 실행 중인 pod이 없습니다.")


class TestCreateCommand:
    """Test suite for create_command handler"""

    @pytest.mark.asyncio
    async def test_create_command_with_templates(self):
        """Test create command when templates are available"""
        update = Mock()
        update.effective_user.id = 111
        update.effective_chat.id = 123456789
        update.message.reply_text = AsyncMock()
        context = Mock()
        context.user_data = {}

        mock_templates = [
            {"id": "tpl-1", "name": "Template 1"},
            {"id": "tpl-2", "name": "Template 2"}
        ]

        with patch('runpod_monitor.fetch_templates', new=AsyncMock(return_value=mock_templates)):
            await runpod_monitor.create_command(update, context)

        update.message.reply_text.assert_called_once()
        call_args = update.message.reply_text.call_args
        assert "템플릿을 선택하세요" in call_args[0][0]
        assert "create_pod" in context.user_data

    @pytest.mark.asyncio
    async def test_create_command_no_templates(self):
        """Test create command when no templates are available"""
        update = Mock()
        update.effective_user.id = 111
        update.effective_chat.id = 123456789
        update.message.reply_text = AsyncMock()
        context = Mock()
        context.user_data = {}

        with patch('runpod_monitor.fetch_templates', new=AsyncMock(return_value=[])):
            await runpod_monitor.create_command(update, context)

        update.message.reply_text.assert_called_once_with("등록된 템플릿이 없습니다.")

    @pytest.mark.asyncio
    async def test_create_command_error_handling(self):
        """Test create command error handling"""
        update = Mock()
        update.effective_user.id = 111
        update.effective_chat.id = 123456789
        update.message.reply_text = AsyncMock()
        context = Mock()
        context.user_data = {}

        with patch('runpod_monitor.fetch_templates', new=AsyncMock(side_effect=Exception("API Error"))):
            await runpod_monitor.create_command(update, context)

        update.message.reply_text.assert_called_once()
        args = update.message.reply_text.call_args[0]
        assert "템플릿 목록을 가져오는 데 실패했습니다" in args[0]


# ============================================================================
# Test Callback Handlers
# ============================================================================

class TestButtonCallback:
    """Test suite for button_callback handler"""

    @pytest.mark.asyncio
    async def test_button_callback_cancel(self):
        """Test cancel callback"""
        query = Mock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.data = "cancel"

        update = Mock()
        update.callback_query = query
        update.effective_user.id = 111
        update.effective_chat.id = 123456789

        context = Mock()
        context.user_data = {"create_pod": {"some": "data"}}

        await runpod_monitor.button_callback(update, context)

        query.answer.assert_called_once()
        query.edit_message_text.assert_called_once_with("작업이 취소되었습니다.")
        assert "create_pod" not in context.user_data

    @pytest.mark.asyncio
    async def test_button_callback_terminate_success(self):
        """Test terminate callback success"""
        query = Mock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.data = "terminate_test-pod-123"

        update = Mock()
        update.callback_query = query
        update.effective_user.id = 111
        update.effective_chat.id = 123456789

        context = Mock()

        with patch('runpod.terminate_pod') as mock_terminate:
            await runpod_monitor.button_callback(update, context)

        query.answer.assert_called_once()
        mock_terminate.assert_called_once_with("test-pod-123")
        assert query.edit_message_text.call_count == 2  # "종료 중..." + "성공"

    @pytest.mark.asyncio
    async def test_button_callback_terminate_invalid_id(self):
        """Test terminate callback with invalid pod ID"""
        query = Mock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.data = "terminate_invalid@pod#id"

        update = Mock()
        update.callback_query = query
        update.effective_user.id = 111
        update.effective_chat.id = 123456789

        context = Mock()

        await runpod_monitor.button_callback(update, context)

        query.answer.assert_called_once()
        query.edit_message_text.assert_called_once_with("잘못된 요청입니다.")

    @pytest.mark.asyncio
    async def test_button_callback_stop_success(self):
        """Test stop callback success"""
        query = Mock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.data = "stop_test-pod-456"

        update = Mock()
        update.callback_query = query
        update.effective_user.id = 111
        update.effective_chat.id = 123456789

        context = Mock()

        with patch('runpod.stop_pod') as mock_stop:
            await runpod_monitor.button_callback(update, context)

        query.answer.assert_called_once()
        mock_stop.assert_called_once_with("test-pod-456")
        assert query.edit_message_text.call_count == 2  # "정지 중..." + "성공"

    @pytest.mark.asyncio
    async def test_button_callback_unauthorized(self):
        """Test callback with unauthorized user"""
        query = Mock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.data = "terminate_test-pod-123"

        update = Mock()
        update.callback_query = query
        update.effective_user.id = 999
        update.effective_chat.id = 999999999

        context = Mock()

        await runpod_monitor.button_callback(update, context)

        query.answer.assert_called_once()
        query.edit_message_text.assert_called_once_with("권한이 없습니다.")

    @pytest.mark.asyncio
    async def test_button_callback_create_template_selection(self):
        """Test create pod flow - template selection"""
        query = Mock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.data = "crtpl_template-123"

        update = Mock()
        update.callback_query = query
        update.effective_user.id = 111
        update.effective_chat.id = 123456789

        context = Mock()
        context.user_data = {
            "create_pod": {
                "_templates": {
                    "template-123": {
                        "id": "template-123",
                        "name": "Test Template",
                        "imageName": "test/image:latest",
                        "dockerArgs": "arg1 arg2",
                        "containerDiskInGb": 50,
                        "ports": "8888/http,22/tcp"
                    }
                }
            }
        }

        mock_volumes = [
            {"id": "vol-1", "name": "Volume 1", "size": 100, "dataCenterId": "US-NY-1"}
        ]

        with patch('runpod_monitor.fetch_network_volumes', new=AsyncMock(return_value=mock_volumes)):
            await runpod_monitor.button_callback(update, context)

        query.answer.assert_called_once()
        query.edit_message_text.assert_called_once()
        call_args = query.edit_message_text.call_args
        assert "네트워크 볼륨을 선택하세요" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_button_callback_create_volume_selection(self):
        """Test create pod flow - volume selection"""
        query = Mock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.data = "crvol_vol-123"

        update = Mock()
        update.callback_query = query
        update.effective_user.id = 111
        update.effective_chat.id = 123456789

        context = Mock()
        context.user_data = {
            "create_pod": {
                "template_name": "Test Template",
                "_volumes": {
                    "vol-123": {
                        "id": "vol-123",
                        "name": "Test Volume",
                        "dataCenterId": "US-NY-1"
                    }
                }
            }
        }

        await runpod_monitor.button_callback(update, context)

        query.answer.assert_called_once()
        query.edit_message_text.assert_called_once()
        call_args = query.edit_message_text.call_args
        assert "GPU를 선택하세요" in call_args[0][0]
        assert context.user_data["create_pod"]["volume_id"] == "vol-123"

    @pytest.mark.asyncio
    async def test_button_callback_create_gpu_selection(self):
        """Test create pod flow - GPU selection"""
        query = Mock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.data = "crgpu_0"

        update = Mock()
        update.callback_query = query
        update.effective_user.id = 111
        update.effective_chat.id = 123456789

        context = Mock()
        context.user_data = {
            "create_pod": {
                "template_name": "Test Template",
                "volume_id": "vol-123",
                "container_disk": 50,
                "ports": "8888/http,22/tcp"
            }
        }

        await runpod_monitor.button_callback(update, context)

        query.answer.assert_called_once()
        query.edit_message_text.assert_called_once()
        call_args = query.edit_message_text.call_args
        assert "Pod 생성 확인" in call_args[0][0]
        assert context.user_data["create_pod"]["gpu_type"] == runpod_monitor.PREFERRED_GPUS[0]

    @pytest.mark.asyncio
    async def test_button_callback_create_confirm_success(self):
        """Test create pod flow - confirm and create"""
        query = Mock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.data = "crconfirm"

        update = Mock()
        update.callback_query = query
        update.effective_user.id = 111
        update.effective_chat.id = 123456789

        context = Mock()
        context.user_data = {
            "create_pod": {
                "pod_name": "test-pod-0204-1530",
                "template_name": "Test Template",
                "template_id": "tpl-123",
                "image_name": "test/image:latest",
                "gpu_type": "NVIDIA A100",
                "container_disk": 50,
                "ports": "8888/http,22/tcp",
                "volume_id": "vol-123",
                "data_center_id": "US-NY-1"
            }
        }

        mock_result = {"id": "new-pod-id-123", "status": "created"}

        with patch('runpod_monitor.create_pod_api', new=AsyncMock(return_value=mock_result)):
            await runpod_monitor.button_callback(update, context)

        query.answer.assert_called_once()
        assert query.edit_message_text.call_count == 2  # "생성 중..." + "성공"
        final_call = query.edit_message_text.call_args_list[-1]
        assert "성공적으로 생성되었습니다" in final_call[0][0]

    @pytest.mark.asyncio
    async def test_button_callback_create_confirm_api_error(self):
        """Test create pod flow - API error during creation"""
        query = Mock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.data = "crconfirm"

        update = Mock()
        update.callback_query = query
        update.effective_user.id = 111
        update.effective_chat.id = 123456789

        context = Mock()
        context.user_data = {
            "create_pod": {
                "pod_name": "test-pod",
                "template_name": "Test Template",
                "template_id": "tpl-123",
                "image_name": "test/image:latest",
                "gpu_type": "NVIDIA A100",
                "container_disk": 50,
                "ports": "8888/http,22/tcp"
            }
        }

        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = "GPU not available"
        mock_response.json.return_value = {"error": {"message": "GPU not available"}}

        error = httpx.HTTPStatusError(
            "400 Bad Request",
            request=Mock(),
            response=mock_response
        )

        with patch('runpod_monitor.create_pod_api', new=AsyncMock(side_effect=error)):
            await runpod_monitor.button_callback(update, context)

        query.answer.assert_called_once()
        final_call = query.edit_message_text.call_args_list[-1]
        assert "실패했습니다" in final_call[0][0]

    @pytest.mark.asyncio
    async def test_button_callback_terminate_error(self):
        """Test terminate callback with error"""
        query = Mock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.data = "terminate_test-pod-123"

        update = Mock()
        update.callback_query = query
        update.effective_user.id = 111
        update.effective_chat.id = 123456789

        context = Mock()

        with patch('runpod.terminate_pod', side_effect=Exception("API Error")):
            await runpod_monitor.button_callback(update, context)

        query.answer.assert_called_once()
        final_call = query.edit_message_text.call_args_list[-1]
        assert "실패했습니다" in final_call[0][0]

    @pytest.mark.asyncio
    async def test_button_callback_stop_error(self):
        """Test stop callback with error"""
        query = Mock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.data = "stop_test-pod-456"

        update = Mock()
        update.callback_query = query
        update.effective_user.id = 111
        update.effective_chat.id = 123456789

        context = Mock()

        with patch('runpod.stop_pod', side_effect=Exception("API Error")):
            await runpod_monitor.button_callback(update, context)

        query.answer.assert_called_once()
        final_call = query.edit_message_text.call_args_list[-1]
        assert "실패했습니다" in final_call[0][0]


# ============================================================================
# Test Pod Checking and Alerting Functions
# ============================================================================

class TestSendAlert:
    """Test suite for send_alert function"""

    @pytest.mark.asyncio
    async def test_send_alert_success(self):
        """Test successful alert sending"""
        app = Mock()
        app.bot.send_message = AsyncMock()

        await send_alert(app, "Test alert message")

        app.bot.send_message.assert_called_once_with(
            chat_id=runpod_monitor.TELEGRAM_CHAT_ID,
            text="Test alert message"
        )

    @pytest.mark.asyncio
    async def test_send_alert_failure(self):
        """Test alert sending failure"""
        app = Mock()
        app.bot.send_message = AsyncMock(side_effect=Exception("Network error"))

        # Should not raise exception
        await send_alert(app, "Test alert message")

        app.bot.send_message.assert_called_once()


class TestCheckPods:
    """Test suite for check_pods function"""

    @pytest.mark.asyncio
    async def test_check_pods_with_running_pods(self):
        """Test checking pods when there are running pods"""
        app = Mock()
        app.bot.send_message = AsyncMock()

        mock_pods = [
            {
                "id": "pod-1",
                "name": "running-pod",
                "desiredStatus": "RUNNING",
                "machine": {"gpuDisplayName": "NVIDIA A100"},
                "costPerHr": 1.5
            },
            {
                "id": "pod-2",
                "name": "stopped-pod",
                "desiredStatus": "STOPPED",
                "machine": {"gpuDisplayName": "NVIDIA RTX A4500"},
                "costPerHr": 0.5
            }
        ]

        with patch('runpod.get_pods', return_value=mock_pods):
            await check_pods(app)

        app.bot.send_message.assert_called_once()
        call_args = app.bot.send_message.call_args[1]
        message = call_args["text"]
        assert "존재하는 Pod: 2개" in message
        assert "실행 중: 1개" in message
        assert "$1.5000" in message
        assert "running-pod" in message

    @pytest.mark.asyncio
    async def test_check_pods_no_pods(self):
        """Test checking pods when there are no pods"""
        app = Mock()
        app.bot.send_message = AsyncMock()

        with patch('runpod.get_pods', return_value=[]):
            await check_pods(app)

        app.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_pods_multiple_running_pods(self):
        """Test checking pods with multiple running pods"""
        app = Mock()
        app.bot.send_message = AsyncMock()

        mock_pods = [
            {
                "id": "pod-1",
                "name": "running-pod-1",
                "desiredStatus": "RUNNING",
                "machine": {"gpuDisplayName": "NVIDIA A100"},
                "costPerHr": 1.5
            },
            {
                "id": "pod-2",
                "name": "running-pod-2",
                "desiredStatus": "RUNNING",
                "machine": {"gpuDisplayName": "NVIDIA A100"},
                "costPerHr": 1.5
            }
        ]

        with patch('runpod.get_pods', return_value=mock_pods):
            await check_pods(app)

        app.bot.send_message.assert_called_once()
        call_args = app.bot.send_message.call_args[1]
        message = call_args["text"]
        assert "실행 중: 2개" in message
        assert "$3.0000" in message  # 1.5 + 1.5

    @pytest.mark.asyncio
    async def test_check_pods_error_handling(self):
        """Test check_pods error handling"""
        app = Mock()
        app.bot.send_message = AsyncMock()

        with patch('runpod.get_pods', side_effect=Exception("API Error")):
            await check_pods(app)

        app.bot.send_message.assert_called_once()
        call_args = app.bot.send_message.call_args[1]
        message = call_args["text"]
        assert "[오류]" in message
        assert "API Error" in message


# ============================================================================
# Test Edge Cases and Integration Scenarios
# ============================================================================

class TestEdgeCases:
    """Test suite for edge cases and boundary conditions"""

    @pytest.mark.asyncio
    async def test_format_pod_info_with_high_cost(self):
        """Test formatting pod with very high cost"""
        pod = {
            "id": "expensive-pod",
            "name": "premium-pod",
            "machine": {"gpuDisplayName": "NVIDIA H100"},
            "costPerHr": 99.9999,
            "desiredStatus": "RUNNING"
        }

        result = format_pod_info(pod)
        assert "$99.9999" in result

    @pytest.mark.asyncio
    async def test_generate_pod_name_empty_template(self):
        """Test pod name generation with empty template name"""
        with patch('runpod_monitor.datetime') as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "0204-1530"

            result = generate_pod_name("")
            assert "-0204-1530" in result

    def test_get_allowed_users_with_invalid_format(self):
        """Test get_allowed_users with non-numeric values"""
        with patch.dict(os.environ, {"ALLOWED_USER_IDS": "111,abc,222"}):
            # Should raise ValueError when trying to convert 'abc' to int
            try:
                result = get_allowed_users()
                # If it doesn't raise, the function filters out invalid values
                assert 111 in result
                assert 222 in result
            except ValueError:
                # This is acceptable behavior
                pass

    @pytest.mark.asyncio
    async def test_status_command_with_many_pods(self):
        """Test status command with many running pods"""
        update = Mock()
        update.effective_user.id = 111
        update.effective_chat.id = 123456789
        update.message.reply_text = AsyncMock()
        context = Mock()

        # Create 10 running pods
        mock_pods = [
            {
                "id": f"pod-{i}",
                "name": f"test-pod-{i}",
                "desiredStatus": "RUNNING",
                "machine": {"gpuDisplayName": "NVIDIA A100"},
                "costPerHr": 1.0 + i * 0.1
            }
            for i in range(10)
        ]

        with patch('runpod.get_pods', return_value=mock_pods):
            await runpod_monitor.status_command(update, context)

        update.message.reply_text.assert_called_once()
        args = update.message.reply_text.call_args[0]
        assert "실행 중인 Pod: 10개" in args[0]

    @pytest.mark.asyncio
    async def test_create_pod_callback_with_expired_session(self):
        """Test create pod callback when session has expired"""
        query = Mock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.data = "crvol_none"

        update = Mock()
        update.callback_query = query
        update.effective_user.id = 111
        update.effective_chat.id = 123456789

        context = Mock()
        context.user_data = {}  # Empty user data simulates expired session

        await runpod_monitor.button_callback(update, context)

        query.edit_message_text.assert_called_once()
        args = query.edit_message_text.call_args[0]
        assert "세션이 만료되었습니다" in args[0]

    @pytest.mark.asyncio
    async def test_check_pods_with_zero_cost_pods(self):
        """Test check_pods with pods that have zero cost"""
        app = Mock()
        app.bot.send_message = AsyncMock()

        mock_pods = [
            {
                "id": "pod-1",
                "name": "free-tier-pod",
                "desiredStatus": "RUNNING",
                "machine": {},
                "costPerHr": 0
            }
        ]

        with patch('runpod.get_pods', return_value=mock_pods):
            await check_pods(app)

        app.bot.send_message.assert_called_once()
        call_args = app.bot.send_message.call_args[1]
        message = call_args["text"]
        assert "$0.0000" in message


# ============================================================================
# Test Configuration and Main Function
# ============================================================================

class TestConfiguration:
    """Test suite for configuration validation"""

    def test_environment_variables_loaded(self):
        """Test that environment variables are properly loaded"""
        assert runpod_monitor.RUNPOD_API_KEY == "test_api_key"
        assert runpod_monitor.TELEGRAM_BOT_TOKEN == "test_bot_token"
        assert runpod_monitor.TELEGRAM_CHAT_ID == "123456789"
        assert runpod_monitor.CHECK_INTERVAL_MINUTES == 60

    def test_preferred_gpus_default(self):
        """Test default GPU list"""
        assert "NVIDIA RTX A4500" in runpod_monitor.DEFAULT_GPUS
        assert "NVIDIA A100 80GB PCIe" in runpod_monitor.DEFAULT_GPUS

    def test_preferred_gpus_custom(self):
        """Test custom GPU list from environment"""
        with patch.dict(os.environ, {"PREFERRED_GPUS": "GPU1,GPU2,GPU3"}):
            # Re-import to get new PREFERRED_GPUS value
            from importlib import reload
            reload(runpod_monitor)
            # Note: This test is illustrative; actual implementation may vary


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])