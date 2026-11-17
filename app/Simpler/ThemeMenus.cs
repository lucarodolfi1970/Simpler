using System.Windows;
using System.Windows.Markup;

namespace Simpler
{
    /// <summary>Dark menus, tooltips and scroll bars for the whole app (the Windows defaults are white).</summary>
    public static class ThemeMenus
    {
        const string Xaml = @"
<ResourceDictionary xmlns='http://schemas.microsoft.com/winfx/2006/xaml/presentation'
                    xmlns:x='http://schemas.microsoft.com/winfx/2006/xaml'>
  <Style TargetType='{x:Type ContextMenu}'>
    <Setter Property='SnapsToDevicePixels' Value='True'/>
    <Setter Property='HasDropShadow' Value='True'/>
    <Setter Property='FontFamily' Value='Segoe UI Variable Text, Segoe UI'/>
    <Setter Property='FontSize' Value='13'/>
    <Setter Property='Foreground' Value='#E4EAF4'/>
    <Setter Property='Template'>
      <Setter.Value>
        <ControlTemplate TargetType='{x:Type ContextMenu}'>
          <Border Background='#12203A' BorderBrush='#22355A' BorderThickness='1' CornerRadius='8' Padding='4' MinWidth='190' MaxHeight='560'>
            <Border.Effect><DropShadowEffect BlurRadius='18' ShadowDepth='4' Opacity='0.5' Color='#000000'/></Border.Effect>
            <ScrollViewer VerticalScrollBarVisibility='Auto' HorizontalScrollBarVisibility='Disabled' CanContentScroll='False'>
              <ItemsPresenter KeyboardNavigation.DirectionalNavigation='Cycle'/>
            </ScrollViewer>
          </Border>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>
  <Style TargetType='{x:Type MenuItem}'>
    <Setter Property='Foreground' Value='#E4EAF4'/>
    <Setter Property='Cursor' Value='Hand'/>
    <Setter Property='Template'>
      <Setter.Value>
        <ControlTemplate TargetType='{x:Type MenuItem}'>
          <Grid>
            <Border x:Name='Bd' Background='Transparent' CornerRadius='6' Padding='12,7,14,7'>
              <DockPanel>
                <Path x:Name='Arrow' DockPanel.Dock='Right' Data='M0,0 L4,4 L0,8' Stroke='#7C8BA6' StrokeThickness='1.5'
                      Margin='18,0,0,0' VerticalAlignment='Center' Visibility='Collapsed'/>
                <TextBlock DockPanel.Dock='Right' Text='{TemplateBinding InputGestureText}' Foreground='#7C8BA6' Margin='24,0,0,0' VerticalAlignment='Center'/>
                <ContentPresenter x:Name='Ic' ContentSource='Icon' DockPanel.Dock='Left' Margin='0,0,10,0' VerticalAlignment='Center'/>
                <ContentPresenter ContentSource='Header' RecognizesAccessKey='True' VerticalAlignment='Center'/>
              </DockPanel>
            </Border>
            <Popup x:Name='PART_Popup' Placement='Right' HorizontalOffset='6' VerticalOffset='-5' AllowsTransparency='True' Focusable='False'
                   PopupAnimation='Fade' IsOpen='{Binding IsSubmenuOpen, RelativeSource={RelativeSource TemplatedParent}}'>
              <Border Background='#12203A' BorderBrush='#22355A' BorderThickness='1' CornerRadius='8' Padding='4' MinWidth='190' MaxHeight='520'>
                <ScrollViewer VerticalScrollBarVisibility='Auto' HorizontalScrollBarVisibility='Disabled'>
                  <ItemsPresenter KeyboardNavigation.DirectionalNavigation='Cycle'/>
                </ScrollViewer>
              </Border>
            </Popup>
          </Grid>
          <ControlTemplate.Triggers>
            <Trigger Property='HasItems' Value='True'>
              <Setter TargetName='Arrow' Property='Visibility' Value='Visible'/>
            </Trigger>
            <Trigger Property='Icon' Value='{x:Null}'>
              <Setter TargetName='Ic' Property='Visibility' Value='Collapsed'/>
            </Trigger>
            <Trigger Property='IsHighlighted' Value='True'>
              <Setter TargetName='Bd' Property='Background' Value='#1D3766'/>
            </Trigger>
            <Trigger Property='IsSubmenuOpen' Value='True'>
              <Setter TargetName='Bd' Property='Background' Value='#1D3766'/>
            </Trigger>
            <Trigger Property='IsEnabled' Value='False'>
              <Setter Property='Opacity' Value='0.45'/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>
  <Style x:Key='{x:Static MenuItem.SeparatorStyleKey}' TargetType='{x:Type Separator}'>
    <Setter Property='Template'>
      <Setter.Value>
        <ControlTemplate TargetType='{x:Type Separator}'>
          <Border Height='1' Margin='8,4' Background='#22355A'/>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>
  <Style TargetType='{x:Type ToolTip}'>
    <Setter Property='Foreground' Value='#E4EAF4'/>
    <Setter Property='FontSize' Value='12'/>
    <Setter Property='Template'>
      <Setter.Value>
        <ControlTemplate TargetType='{x:Type ToolTip}'>
          <Border Background='#12203A' BorderBrush='#22355A' BorderThickness='1' CornerRadius='6' Padding='10,6' MaxWidth='360'>
            <ContentPresenter>
              <ContentPresenter.Resources>
                <Style TargetType='{x:Type TextBlock}'><Setter Property='TextWrapping' Value='Wrap'/></Style>
              </ContentPresenter.Resources>
            </ContentPresenter>
          </Border>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>
</ResourceDictionary>";
        const string ScrollXaml = @"
<ResourceDictionary xmlns='http://schemas.microsoft.com/winfx/2006/xaml/presentation'
                    xmlns:x='http://schemas.microsoft.com/winfx/2006/xaml'>
  <Style x:Key='SimplerThumb' TargetType='{x:Type Thumb}'>
    <Setter Property='Template'>
      <Setter.Value>
        <ControlTemplate TargetType='{x:Type Thumb}'>
          <Border x:Name='T' Background='#2A3D63' CornerRadius='4'/>
          <ControlTemplate.Triggers>
            <Trigger Property='IsMouseOver' Value='True'><Setter TargetName='T' Property='Background' Value='#3A5487'/></Trigger>
            <Trigger Property='IsDragging' Value='True'><Setter TargetName='T' Property='Background' Value='#4C9DFF'/></Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>
  <Style x:Key='SimplerPage' TargetType='{x:Type RepeatButton}'>
    <Setter Property='Focusable' Value='False'/>
    <Setter Property='Template'>
      <Setter.Value>
        <ControlTemplate TargetType='{x:Type RepeatButton}'><Border Background='Transparent'/></ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>
  <Style TargetType='{x:Type ScrollBar}'>
    <Setter Property='Background' Value='Transparent'/>
    <Setter Property='Width' Value='10'/>
    <Setter Property='MinWidth' Value='10'/>
    <Setter Property='Template'>
      <Setter.Value>
        <ControlTemplate TargetType='{x:Type ScrollBar}'>
          <Border Background='#0A1222' Padding='2'>
            <Track x:Name='PART_Track' IsDirectionReversed='True'>
              <Track.DecreaseRepeatButton><RepeatButton Style='{StaticResource SimplerPage}' Command='ScrollBar.PageUpCommand'/></Track.DecreaseRepeatButton>
              <Track.IncreaseRepeatButton><RepeatButton Style='{StaticResource SimplerPage}' Command='ScrollBar.PageDownCommand'/></Track.IncreaseRepeatButton>
              <Track.Thumb><Thumb Style='{StaticResource SimplerThumb}' MinHeight='28'/></Track.Thumb>
            </Track>
          </Border>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
    <Style.Triggers>
      <Trigger Property='Orientation' Value='Horizontal'>
        <Setter Property='Width' Value='Auto'/>
        <Setter Property='MinWidth' Value='0'/>
        <Setter Property='Height' Value='10'/>
        <Setter Property='MinHeight' Value='10'/>
        <Setter Property='Template'>
          <Setter.Value>
            <ControlTemplate TargetType='{x:Type ScrollBar}'>
              <Border Background='#0A1222' Padding='2'>
                <Track x:Name='PART_Track' IsDirectionReversed='False'>
                  <Track.DecreaseRepeatButton><RepeatButton Style='{StaticResource SimplerPage}' Command='ScrollBar.PageLeftCommand'/></Track.DecreaseRepeatButton>
                  <Track.IncreaseRepeatButton><RepeatButton Style='{StaticResource SimplerPage}' Command='ScrollBar.PageRightCommand'/></Track.IncreaseRepeatButton>
                  <Track.Thumb><Thumb Style='{StaticResource SimplerThumb}' MinWidth='28'/></Track.Thumb>
                </Track>
              </Border>
            </ControlTemplate>
          </Setter.Value>
        </Setter>
      </Trigger>
    </Style.Triggers>
  </Style>
  <Style TargetType='{x:Type ScrollViewer}'>
    <Setter Property='Template'>
      <Setter.Value>
        <ControlTemplate TargetType='{x:Type ScrollViewer}'>
          <Grid>
            <Grid.ColumnDefinitions><ColumnDefinition Width='*'/><ColumnDefinition Width='Auto'/></Grid.ColumnDefinitions>
            <Grid.RowDefinitions><RowDefinition Height='*'/><RowDefinition Height='Auto'/></Grid.RowDefinitions>
            <ScrollContentPresenter x:Name='PART_ScrollContentPresenter' CanContentScroll='{TemplateBinding CanContentScroll}' Margin='{TemplateBinding Padding}'/>
            <ScrollBar x:Name='PART_VerticalScrollBar' Grid.Column='1' Orientation='Vertical'
                       Maximum='{TemplateBinding ScrollableHeight}' ViewportSize='{TemplateBinding ViewportHeight}'
                       Value='{Binding VerticalOffset, RelativeSource={RelativeSource TemplatedParent}, Mode=OneWay}'
                       Visibility='{TemplateBinding ComputedVerticalScrollBarVisibility}'/>
            <ScrollBar x:Name='PART_HorizontalScrollBar' Grid.Row='1' Orientation='Horizontal'
                       Maximum='{TemplateBinding ScrollableWidth}' ViewportSize='{TemplateBinding ViewportWidth}'
                       Value='{Binding HorizontalOffset, RelativeSource={RelativeSource TemplatedParent}, Mode=OneWay}'
                       Visibility='{TemplateBinding ComputedHorizontalScrollBarVisibility}'/>
            <Border Grid.Column='1' Grid.Row='1' Background='#0A1222'/>
          </Grid>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>
</ResourceDictionary>";


        public static void Install(Application app)
        {
            // each group on its own: a style that fails never blocks the start of the app (Windows look instead)
            foreach (var xaml in new[] { Xaml, ScrollXaml })
            {
                try { app.Resources.MergedDictionaries.Add((ResourceDictionary)XamlReader.Parse(xaml)); }
                catch (System.Exception ex) { System.Diagnostics.Debug.WriteLine("Simpler styles: " + ex.Message); }
            }
        }
    }
}
